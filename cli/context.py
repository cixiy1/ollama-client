"""上下文文件感知 — 自动发现并加载项目规范文件"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator


# ---- 默认感知路径（参考 OpenCode defaultContextPaths） ----

CONTEXT_PATTERNS = [
    # 项目规范
    ".github/copilot-instructions.md",
    ".cursorrules",
    ".cursor/rules/",            # 目录，读取下所有 .md 文件
    "CLAUDE.md",
    "CLAUDE.local.md",
    "YUKI.md",
    "YUKI.local.md",
    "GEMINI.md",
    "GEMINI.local.md",
    # IDE/编辑器配置
    ".claude",
    ".windsurfrc",
    ".windsurf",
    "windsurf.md",
    # 其他通用 AI 规范
    "opencode.md",
    "opencode.local.md",
    "agent.md",
    ".context.md",
    # 根目录配置
    "README.md",
]

# 目录类模式（递归搜索该目录下所有 .md 文件）
DIRECTORY_PATTERNS = {
    ".cursor/rules/",
    "rules/",
    ".windsurf/",
}


@dataclass
class ContextFile:
    """感知到的上下文文件"""
    path: Path
    content: str
    source: str           # 文件名（含路径）
    priority: int         # 优先级（越小越重要）


from dataclasses import dataclass


def _load_text(path: Path, max_size: int = 200_000) -> str | None:
    """安全读取文本文件，限制大小"""
    try:
        if not path.exists() or not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_size:
            return None  # 太大跳过
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _iter_files_from_dir(root: Path, subdir: str) -> Iterator[Path]:
    """递归列出子目录下所有 .md 文件"""
    base = root / subdir.strip("/")
    if not base.is_dir():
        return
    for p in base.rglob("*.md"):
        if p.is_file():
            yield p
    for p in base.rglob("*"):
        if p.is_file() and p.suffix not in (".md",):
            yield p


def discover_context_files(
    cwd: str | Path | None = None,
    patterns: list[str] | None = None,
    max_total_chars: int = 80_000,
) -> list[ContextFile]:
    """
    在指定目录下搜索上下文文件。

    参考 OpenCode 的 defaultContextPaths 自动加载项目规范。

    Args:
        cwd: 工作目录，默认为当前目录
        patterns: 自定义感知路径列表（None 使用默认）
        max_total_chars: 最多读取多少字符（防止上下文爆炸）

    Returns:
        按优先级排序的 ContextFile 列表
    """
    if cwd is None:
        cwd = Path.cwd()
    root = Path(cwd).resolve()

    if patterns is None:
        patterns = CONTEXT_PATTERNS

    found: list[ContextFile] = []
    total_chars = 0

    for i, pattern in enumerate(patterns):
        if total_chars >= max_total_chars:
            break

        if pattern.endswith("/"):
            # 目录模式
            for p in _iter_files_from_dir(root, pattern):
                content = _load_text(p)
                if content:
                    chars = len(content)
                    if total_chars + chars <= max_total_chars:
                        found.append(ContextFile(
                            path=p,
                            content=content,
                            source=str(p.relative_to(root)) if p.is_relative_to(root) else str(p),
                            priority=i,
                        ))
                        total_chars += chars
        else:
            p = root / pattern
            content = _load_text(p)
            if content:
                chars = len(content)
                if total_chars + chars <= max_total_chars:
                    found.append(ContextFile(
                        path=p,
                        content=content,
                        source=pattern,
                        priority=i,
                    ))
                    total_chars += chars

    # 按优先级排序
    found.sort(key=lambda x: x.priority)
    return found


def build_system_prompt(contexts: list[ContextFile]) -> str:
    """
    将上下文文件构建为系统提示词片段。

    返回格式：
    --- project_context.md ---
    [文件名]
    [内容]
    ...
    """
    if not contexts:
        return ""

    parts = [
        "--- 项目上下文文件（自动加载，请遵守其中规范） ---\n"
    ]
    for ctx in contexts:
        rel = ctx.source
        parts.append(f"\n[{rel}]\n{ctx.content}\n")
    return "".join(parts)


def inject_into_messages(
    contexts: list[ContextFile],
    messages: list[dict],
) -> list[dict]:
    """
    将上下文文件注入到 messages 中。
    在第一条 system 消息之前插入 context 内容。
    """
    if not contexts:
        return messages

    context_text = build_system_prompt(contexts)
    if not context_text:
        return messages

    injected = []
    system_injected = False
    for msg in messages:
        if msg.get("role") == "system" and not system_injected:
            # 合并到现有的 system 消息
            new_content = context_text + "\n\n" + msg.get("content", "")
            injected.append({**msg, "content": new_content})
            system_injected = True
        else:
            injected.append(msg)

    if not system_injected:
        # 没有 system 消息，插入到最前面
        injected.insert(0, {"role": "system", "content": context_text})

    return injected


# ---- 便捷函数 ----

def load_context_for_directory(cwd: str | Path | None = None) -> str:
    """直接返回拼接好的上下文字符串，供 API 调用"""
    contexts = discover_context_files(cwd)
    return build_system_prompt(contexts)


# ---- 打印友好的上下文摘要 ----

def summarize_contexts(contexts: list[ContextFile]) -> str:
    """生成上下文加载摘要（用于提示用户）"""
    if not contexts:
        return "  (未发现上下文规范文件)"
    lines = []
    for ctx in contexts:
        size = len(ctx.content)
        lines.append(f"  + {ctx.source}  ({size:,} 字)")
    return "\n".join(lines)
