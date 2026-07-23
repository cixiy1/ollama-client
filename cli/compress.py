"""上下文压缩 — LLM 摘要 + 工具对保护 + 自动压缩 + 会话修剪"""

from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from cli.session import Message

if TYPE_CHECKING:
    from cli.api import YukiAPI


# ── 粗略 Token 估算 ──────────────────────────────────────────

_TOKENIZER_CACHE: dict[str, "tiktoken.Encoding | None"] = {}


def _count_tokens(text: str, model_hint: str = "gpt-4") -> int:
    """估算文本的 token 数，失败时回退到粗略的字符/4 估算。"""
    try:
        import tiktoken
        # 根据模型名猜编码
        key = "cl100k_base"  # gpt-4 / gpt-3.5 / text-embedding-ada-002
        if model_hint and ("deepseek" in model_hint or "qwen" in model_hint):
            # deepseek 和 qwen 也兼容 cl100k_base
            pass
        if model_hint and ("llama" in model_hint.lower() or "codestral" in model_hint.lower()):
            key = "cl100k_base"  # 仍有合理近似
        if key not in _TOKENIZER_CACHE:
            _TOKENIZER_CACHE[key] = tiktoken.get_encoding(key)
        enc = _TOKENIZER_CACHE[key]
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        pass
    # 保守估算：中文 ~= 1.5 字符/token，英文 ~= 4 字符/token
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return ascii_chars // 4 + non_ascii * 2 // 3 + 1


def estimate_messages_tokens(messages: list[Message], model_hint: str = "") -> int:
    """估算消息列表的总 token 数（含 role/system overhead）"""
    total = 0
    for m in messages:
        total += _count_tokens(m.content, model_hint)
        total += _count_tokens(m.thinking, model_hint)
        total += 4  # role / metadata overhead
    return total


# ── 工具调用/结果配对 ──────────────────────────────────────

@dataclass
class ToolPair:
    """一对工具调用 + 结果"""
    call_msg: Message
    result_msg: Message | None = None


def find_tool_pairs(messages: list[Message]) -> list[ToolPair]:
    """在消息列表中扫描 tool-call / tool-result 配对。
    返回所有找到的完整配对（有 call 也有 result）。"""
    pairs: list[ToolPair] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.role == "assistant" and _has_tool_call(m.content):
            # 找到 tool call，往下找最近的 tool result
            pair = ToolPair(call_msg=m)
            for j in range(i + 1, len(messages)):
                if messages[j].role == "tool":
                    pair.result_msg = messages[j]
                    pairs.append(pair)
                    i = j  # 跳过 result
                    break
                elif messages[j].role == "assistant" and _has_tool_call(messages[j].content):
                    # 连续 tool call（多工具并行调用），也配对
                    break
        i += 1
    return pairs


def _has_tool_call(content: str) -> bool:
    """检测消息是否包含 tool_call"""
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data.get("role") == "assistant" and "tool_calls" in data.get("content", {})
    except (json.JSONDecodeError, TypeError):
        pass
    # 也检查非 JSON 格式（Yuki Code 把 tool_calls 放 assistant content JSON 里）
    if isinstance(content, str) and "tool_calls" in content:
        return True
    return False


# ── 压缩配置 ───────────────────────────────────────────────

DEFAULT_AUTO_COMPACT_THRESHOLD = 30       # 超过此消息数触发自动压缩
DEFAULT_AUTO_COMPACT_KEEP_RECENT = 8      # 自动压缩保留最近几条
DEFAULT_MANUAL_COMPACT_KEEP_RECENT = 3    # 手动 /compact 保留最近几条
DEFAULT_RESERVE_TOKENS = 4096             # 保留给 prompt + 输出的 token 头寸
DEFAULT_MODEL_TOKEN_LIMIT = 32768         # 默认模型上下文窗口（如未查知具体值）


@dataclass
class CompressConfig:
    """压缩策略配置"""
    auto_compact_threshold: int = DEFAULT_AUTO_COMPACT_THRESHOLD
    auto_compact_keep_recent: int = DEFAULT_AUTO_COMPACT_KEEP_RECENT
    manual_compact_keep_recent: int = DEFAULT_MANUAL_COMPACT_KEEP_RECENT
    reserve_tokens: int = DEFAULT_RESERVE_TOKENS
    model_token_limit: int = DEFAULT_MODEL_TOKEN_LIMIT
    # 如果提供 summarization_model，用其生成摘要；否则用对话模型
    summarization_model: str | None = None
    # LLM 总结提示词模板
    summary_prompt_template: str = (
        "请为以下对话生成一段简洁的摘要，保留关键决策和讨论结果。"
        "用户是指令方，助手是执行方。"
        "摘要应包含：\n"
        "1. 主要目标和需求\n"
        "2. 关键决策和技术选择\n"
        "3. 已完成的成果\n"
        "4. 仍待解决的事项\n"
    )


# ── 压缩结果 ───────────────────────────────────────────────

@dataclass
class CompressResult:
    """压缩操作的返回结果"""
    compressed: bool              # 是否实际执行了压缩
    deleted_count: int            # 删除的消息数
    summary: str                  # 生成的摘要文本
    kept_messages: list[Message]  # 保留的消息（含摘要）
    reason: str = ""              # 触发原因（auto/manual）


# ── 主压缩器 ───────────────────────────────────────────────

class ContextCompressor:
    """
    上下文压缩器，负责：
    - 将旧轮次压缩为 LLM 生成的摘要（完整保留
    - 对话的历史以保护工具调用/结果配对，
    - 提供 token 估算以决定是否压缩，
    - 支持 session pruning（轻量级：仅修剪工具输出内容）。
    """

    def __init__(self, config: CompressConfig | None = None):
        self.config = config or CompressConfig()

    # ── 公共 API ──────────────────────────────────────────

    def should_auto_compact(self, messages: list[Message], model_hint: str = "") -> bool:
        """判断是否需要自动压缩。"""
        if not messages:
            return False
        # 规则 1：消息数量超过阈值
        if len(messages) > self.config.auto_compact_threshold:
            return True
        # 规则 2：估算 token 超过上下文窗口 - 保留头寸
        if self.config.model_token_limit > 0:
            current = estimate_messages_tokens(messages, model_hint)
            if current > self.config.model_token_limit - self.config.reserve_tokens:
                return True
        return False

    def compact(
        self,
        messages: list[Message],
        api: YukiAPI | None = None,
        model_hint: str = "",
        keep_recent: int | None = None,
        reason: str = "manual",
    ) -> CompressResult:
        """
        执行上下文压缩。

        1. 确定保留的最近消息数（手动指定或自动阈值）
        2. 扫描旧消息中的 tool pair，确保不对分
        3. 旧消息 → LLM 摘要（如提供 api），否则回退到规则摘要
        4. 返回 CompressResult
        """
        if not messages:
            return CompressResult(
                compressed=False, deleted_count=0, summary="", kept_messages=messages, reason=reason
            )

        k = keep_recent if keep_recent is not None else self.config.manual_compact_keep_recent

        # ── 步骤 1：确定 split point ──
        split_idx = self._find_split_point(messages, k)

        if split_idx == 0:
            # 没有足够的旧消息需要压缩
            return CompressResult(
                compressed=False, deleted_count=0, summary="", kept_messages=messages, reason=reason
            )

        old_msgs = messages[:split_idx]
        kept_msgs = messages[split_idx:]

        # ── 步骤 2：生成摘要 ──
        if api and self.config.summarization_model:
            summary = self._llm_summarize(old_msgs, api, self.config.summarization_model)
        else:
            summary = self._rule_summarize(old_msgs)

        # ── 步骤 3：构建保留的消息（摘要 + 最近消息） ──
        # 摘要作为一个 system 消息放在最前面
        summary_msg = Message(
            role="system",
            content=f"[上下文压缩摘要]\n{summary}",
            model="compressor",
            timestamp=time.time(),
        )
        kept_msgs.insert(0, summary_msg)

        return CompressResult(
            compressed=True,
            deleted_count=len(old_msgs),
            summary=summary,
            kept_messages=kept_msgs,
            reason=reason,
        )

    def prune_tool_results(
        self,
        messages: list[Message],
        max_content_chars: int = 500,
    ) -> list[Message]:
        """
        轻量级 session pruning：缩短 tool role 消息的内容（in-memory）。
        不回写 DB，仅在模型上下文构建前使用。
        """
        pruned: list[Message] = []
        for m in messages:
            if m.role == "tool" and len(m.content) > max_content_chars:
                pruned.append(Message(
                    role=m.role,
                    content=m.content[:max_content_chars]
                    + f"\n... [工具输出过长，已截断，原文 {len(m.content)} 字符]",
                    thinking=m.thinking,
                    model=m.model,
                    timestamp=m.timestamp,
                ))
            else:
                pruned.append(m)
        return pruned

    # ── 内部：split point ─────────────────────────────────

    def _find_split_point(self, messages: list[Message], keep_recent: int) -> int:
        """找到安全的切分点：至少保留 keep_recent 条，且不对分 tool pair。"""
        if len(messages) <= keep_recent:
            return 0

        # 从后往前扫描，找到第一个安全的切分点
        max_keep = min(keep_recent + 5, len(messages))
        for try_keep in range(keep_recent, max_keep + 1):
            split_idx = len(messages) - try_keep
            if split_idx <= 0:
                return 0
            if not self._splits_tool_pair(messages, split_idx):
                return split_idx

        # fallback：找不到完全安全的，就保持原来的 keep_recent
        split_idx = max(0, len(messages) - keep_recent)
        return split_idx

    @staticmethod
    def _splits_tool_pair(messages: list[Message], split_idx: int) -> bool:
        """
        检查 split_idx 是否落在某个 tool pair 中间。
        True = 会拆散一对 → 需要调整。
        """
        if split_idx <= 0 or split_idx >= len(messages):
            return False

        # 检查 split_idx 之前的最后几条消息
        # 如果 split_idx 之前有 assistant(tool_call)，之后有 tool(result)，拆散了
        before = messages[split_idx - 1] if split_idx > 0 else None
        after = messages[split_idx] if split_idx < len(messages) else None

        if before and before.role == "assistant" and _has_tool_call(before.content):
            # 不能拆散：call 在旧区，result 在新区的头
            return True
        if after and after.role == "tool":
            # 不能拆散：result 在新区的头，call 在旧区的尾
            return True

        return False

    # ── 内部：总结 ────────────────────────────────────────

    def _llm_summarize(
        self,
        messages: list[Message],
        api: YukiAPI,
        model: str,
    ) -> str:
        """使用模型生成语义摘要（异步串行调用）。"""
        # 构建总结用的 prompt
        chat_text = "\n".join(
            f"【{m.role.capitalize()}】{m.content[:500]}"
            + ("..." if len(m.content) > 500 else "")
            for m in messages
            if m.role != "system"
        )
        prompt = self.config.summary_prompt_template + "\n\n" + chat_text

        try:
            # 使用非流式 chat 获取摘要
            result = api.chat(model, [{"role": "user", "content": prompt}],
                              temperature=0.3, stream=False)
            if isinstance(result, str):
                return result.strip()
            # 可能是 (type, content) 元组
            if isinstance(result, tuple):
                return result[1].strip() if result[1] else ""
            return str(result).strip()
        except Exception as e:
            return (
                f"[摘要生成失败: {e}]\n"
                + self._rule_summarize(messages)
            )

    @staticmethod
    def _rule_summarize(messages: list[Message]) -> str:
        """回退规则：用关键点拼接摘要（不依赖 LLM）。"""
        if not messages:
            return ""

        user_qs: list[str] = []
        assistant_as: list[str] = []
        tool_ops: list[str] = []

        for m in messages:
            if m.role == "user":
                user_qs.append(m.content[:120].replace("\n", " "))
            elif m.role == "assistant" and not _has_tool_call(m.content):
                assistant_as.append(m.content[:120].replace("\n", " "))
            elif m.role == "assistant" and _has_tool_call(m.content):
                tool_ops.append(f"[调用了工具: {m.content[:80]}]")

        lines: list[str] = ["=== 对话历史摘要 ==="]
        n = max(len(user_qs), len(assistant_as))
        if n > 0:
            lines.append(f"共 {n} 轮对话：")
            for i in range(n):
                u = user_qs[i] if i < len(user_qs) else "(等待回答)"
                a = assistant_as[i] if i < len(assistant_as) else "(工具调用)"
                lines.append(f"{i+1}. 🧑 {u}")
                lines.append(f"   🤖 {a}")
        if tool_ops:
            lines.append(f"\n工具操作 ({len(tool_ops)} 次):")
            for t in tool_ops[:5]:
                lines.append(f"  ⚙ {t}")
            if len(tool_ops) > 5:
                lines.append(f"  ... 还有 {len(tool_ops) - 5} 次")

        return "\n".join(lines)

    # ── 诊断 ──────────────────────────────────────────────

    def analyze(self, messages: list[Message], model_hint: str = "") -> dict:
        """返回上下文分析报告（供调试 /status 使用）"""
        total_msgs = len(messages)
        total_tokens = estimate_messages_tokens(messages, model_hint)
        user_count = sum(1 for m in messages if m.role == "user")
        assistant_count = sum(1 for m in messages if m.role == "assistant")
        tool_count = sum(1 for m in messages if m.role == "tool")
        system_count = sum(1 for m in messages if m.role == "system")
        pairs = find_tool_pairs(messages)

        return {
            "total_messages": total_msgs,
            "estimated_tokens": total_tokens,
            "by_role": {
                "user": user_count,
                "assistant": assistant_count,
                "tool": tool_count,
                "system": system_count,
            },
            "tool_pairs": len(pairs),
            "need_compact": self.should_auto_compact(messages, model_hint),
            "model_token_limit": self.config.model_token_limit,
            "usage_pct": round(total_tokens / max(self.config.model_token_limit, 1) * 100, 1),
        }
