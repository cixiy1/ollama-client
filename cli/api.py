"""Yuki Code — AI 模型调用层，支持多 Provider，统一事件类型"""
from __future__ import annotations

import json
import time
import requests
from dataclasses import dataclass, field
from typing import Iterator

from .config import Provider
from .session import SessionStore, Message as SessionMessage
from .usage import UsageStore, UsageRecord


# ---- 统一事件类型（参考 OpenCode ProviderEvent） ----

class Event:
    """统一流式事件类型 — 不管底层 Provider，上层收到的事件格式一致"""
    THINKING_DELTA  = "thinking_delta"
    THINKING_START  = "thinking_start"
    THINKING_END    = "thinking_end"
    CONTENT_DELTA   = "content_delta"
    CONTENT_START   = "content_start"
    CONTENT_END    = "content_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END   = "tool_call_end"
    USAGE           = "usage"
    COMPLETE        = "complete"
    ERROR           = "error"


@dataclass
class StreamEvent:
    """流式事件封装"""
    type: str = ""
    content: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@dataclass
class ToolCall:
    """归一化后的工具调用（屏蔽 Ollama / OpenAI 格式差异）"""
    id: str = ""
    name: str = ""
    arguments: dict = field(default_factory=dict)
    raw_arguments: str = ""        # 原始 JSON 字符串（OpenAI 回传用）


@dataclass
class ChatResult:
    """非流式单轮对话结果"""
    content: str = ""
    thinking: str = ""
    tool_calls: list = field(default_factory=list)   # list[ToolCall]
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw_message: dict = field(default_factory=dict)  # 原始 assistant 消息（回填对话历史用）


# ---- 数据模型 ----

@dataclass
class Model:
    name: str
    size: int = 0
    modified: str = ""
    digest: str = ""
    context_length: int = 0

    def format_size(self) -> str:
        s = self.size
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if s < 1024:
                return f"{s:.1f} {unit}"
            s /= 1024
        return f"{s:.1f} PB"

    def format_modified(self) -> str:
        return self.modified[:19].replace("T", " ") if self.modified else "未知"


# ---- 文本式工具调用 fallback 解析 ----

import re as _re

_QWEN_TOOLCALL = _re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", _re.DOTALL)
_FENCE_JSON = _re.compile(r"```(?:json|tool_call|tool)?\s*(\{.*?\}|\[.*?\])\s*```", _re.DOTALL)


def _extract_text_tool_calls(content: str, tool_names: set[str]) -> list:
    """
    当模型未返回原生 tool_calls、却把工具调用写成 content 文本时，
    从文本里把工具调用 JSON 解析出来。兼容多种格式：
    - Qwen 风格 <tool_call>{...}</tool_call>
    - 代码块 ```json {...} ```
    - 裸 JSON 对象/数组
    仅当 name 命中已知工具时才视为工具调用，避免误伤。
    """
    if not content or not tool_names:
        return []
    candidates: list[str] = []
    candidates += _QWEN_TOOLCALL.findall(content)
    candidates += _FENCE_JSON.findall(content)
    if not candidates:
        s = content.strip()
        if (s.startswith("{") and s.endswith("}")) or \
           (s.startswith("[") and s.endswith("]")):
            candidates.append(s)
    calls = []
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if not isinstance(o, dict):
                continue
            if "tool_call" in o and isinstance(o["tool_call"], dict):
                o = o["tool_call"]
            name = o.get("name") or o.get("tool") or o.get("function")
            if isinstance(name, dict):
                name = name.get("name")
            args = (o.get("arguments") or o.get("parameters")
                    or o.get("args") or o.get("input") or {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name in tool_names and isinstance(args, dict):
                calls.append(ToolCall(id=str(name), name=str(name), arguments=args))
    return calls


# ---- 思考标签解析 ----

def _split_think(text: str) -> Iterator[tuple[str, str]]:
    """
    将包含<think>...</think>标签的文本拆成 (类型, 片段) 序列。
    类型为 "thinking" 或 "content"。
    """
    while text:
        o = text.find("<think>")
        c = text.find("</think>")
        if o == -1:
            if c != -1:
                text = text[:c] + text[c + len("</think>"):]
                continue
            yield ("content", text)
            return
        if o > 0:
            yield ("content", text[:o])
        after_open = text[o + len("<think>"):]
        c2 = after_open.find("</think>")
        if c2 == -1:
            yield ("thinking", after_open)
            return
        yield ("thinking", after_open[:c2])
        text = after_open[c2 + len("</think>"):]


# ---- Provider API 实现 ----

class YukiAPI:
    """
    统一 API 层，根据 Provider 类型自动选择调用方式：
    - ollama:  原生 Ollama HTTP API
    - openai:  OpenAI 兼容端点 (/v1/chat/completions)
    - custom:  自定义 URL + 自定义端点前缀

    可选注入 SessionStore / UsageStore 以启用：
    - 对话历史持久化
    - Token 用量统计
    """

    def __init__(self, provider: Provider,
                 session_store: SessionStore | None = None,
                 usage_store: UsageStore | None = None):
        self.provider = provider
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if provider.api_key:
            self._session.headers["Authorization"] = f"Bearer {provider.api_key}"
        if provider.extra_headers:
            self._session.headers.update(provider.extra_headers)
        self._session_store = session_store
        self._usage_store = usage_store

    # ---- 通用请求封装 ----

    def _post(self, path: str, payload: dict,
              stream: bool = False, timeout: int | None = None) -> requests.Response:
        url = f"{self.provider.base_url.rstrip('/')}{path}"
        t = timeout if timeout is not None else self.provider.timeout
        return self._session.post(url, json=payload, stream=stream, timeout=t)

    def _get(self, path: str, timeout: int | None = None) -> requests.Response:
        url = f"{self.provider.base_url.rstrip('/')}{path}"
        t = timeout if timeout is not None else self.provider.timeout
        return self._session.get(url, timeout=t)

    def _delete(self, path: str, payload: dict,
                timeout: int | None = None) -> requests.Response:
        url = f"{self.provider.base_url.rstrip('/')}{path}"
        t = timeout if timeout is not None else self.provider.timeout
        return self._session.delete(url, json=payload, timeout=t)

    # ---- 服务检测 ----

    def ping(self) -> bool:
        try:
            r = self._get("/", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ---- 模型列表 ----

    def list_models(self) -> list[Model]:
        if self.provider.type == "ollama":
            return self._list_models_ollama()
        elif self.provider.type in ("openai", "custom"):
            return self._list_models_openai()
        return []

    def _list_models_ollama(self) -> list[Model]:
        r = self._get("/api/tags", timeout=10)
        r.raise_for_status()
        raw = r.json().get("models", [])
        return [
            Model(name=m["name"], size=m.get("size", 0),
                  modified=m.get("modified_at", ""), digest=m.get("digest", ""))
            for m in raw
        ]

    def _list_models_openai(self) -> list[Model]:
        try:
            r = self._get("/v1/models", timeout=10)
            r.raise_for_status()
            data = r.json()
            return [Model(name=m["id"]) for m in data.get("data", [])]
        except requests.RequestException:
            if self.provider.default_model:
                return [Model(name=self.provider.default_model)]
            return []

    # ---- 模型操作（仅 Ollama） ----

    def pull_model(self, name: str) -> Iterator[str]:
        if self.provider.type != "ollama":
            yield f"[{name}] 当前 Provider 类型不支持拉取模型"
            return
        payload = {"name": name, "stream": True}
        try:
            with self._session.post(
                f"{self.provider.base_url}/api/pull",
                json=payload, stream=True, timeout=0
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if "progress" in data:
                            yield f"[{data.get('model', '')}] {status} {data.get('progress', '')}"
                        else:
                            yield status
        except requests.RequestException as e:
            yield f"[拉取失败: {e}]"

    def delete_model(self, name: str) -> bool:
        if self.provider.type != "ollama":
            return False
        try:
            r = self._delete("/api/delete", {"name": name}, timeout=30)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def show_model_info(self, name: str) -> dict:
        if self.provider.type != "ollama":
            return {"error": "当前 Provider 类型不支持查看模型详情"}
        try:
            r = self._post("/api/show", {"name": name}, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def running_models(self) -> list[dict]:
        if self.provider.type != "ollama":
            return []
        try:
            r = self._get("/api/ps", timeout=10)
            r.raise_for_status()
            return r.json().get("models", [])
        except requests.RequestException:
            return []

    # ---- 对话生成（传统 tuple 接口，兼容旧代码） ----

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        stream: bool = True,
        think: bool = True,
    ) -> Iterator[tuple[str, str]]:
        if self.provider.type == "ollama":
            yield from self._chat_ollama(model, messages, temperature, stream, think)
        else:
            yield from self._chat_openai(model, messages, temperature, stream, think)

    def _chat_ollama(
        self, model: str, messages: list[dict],
        temperature: float, stream: bool, think: bool,
    ) -> Iterator[tuple[str, str]]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": temperature},
        }
        if think:
            payload["think"] = True
        try:
            with self._post("/api/chat", payload, stream=stream) as resp:
                if think and resp.status_code == 400:
                    resp.close()
                    yield from self._chat_ollama(model, messages, temperature, stream, think=False)
                    return
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        data = json.loads(line)
                        msg = data.get("message", {})
                        if msg.get("thinking"):
                            yield ("thinking", msg["thinking"])
                        content = msg.get("content", "")
                        if content:
                            for kind, piece in _split_think(content):
                                yield (kind, piece)
        except requests.HTTPError:
            if think:
                yield from self._chat_ollama(model, messages, temperature, stream, think=False)
            else:
                raise

    def _chat_openai(
        self, model: str, messages: list[dict],
        temperature: float, stream: bool, think: bool,
    ) -> Iterator[tuple[str, str]]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        try:
            with self._post("/v1/chat/completions", payload, stream=stream) as resp:
                resp.raise_for_status()
                if stream:
                    for line in resp.iter_lines():
                        if line:
                            line_text = line.decode("utf-8", errors="replace")
                            if line_text.startswith("data: "):
                                data_str = line_text[6:]
                                if data_str.strip() == "[DONE]":
                                    return
                                try:
                                    data = json.loads(data_str)
                                except json.JSONDecodeError:
                                    continue
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    for kind, piece in _split_think(content):
                                        yield (kind, piece)
                else:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        for kind, piece in _split_think(content):
                            yield (kind, piece)
        except requests.RequestException as e:
            yield ("content", f"[请求错误: {e}]")

    # ---- 统一事件流接口（参考 OpenCode StreamResponse） ----

    def stream_events(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        think: bool = True,
    ) -> Iterator[StreamEvent]:
        """
        统一事件流接口，yield StreamEvent。
        对应 OpenCode 的 Provider.StreamResponse。

        上层 UI 只需处理 Event 常量，不需关心底层 Provider 类型。
        """
        start_time = time.time()
        thinking_buf = ""
        content_buf = ""
        think_started = False

        for kind, piece in self.chat(model, messages, temperature,
                                     stream=True, think=think):
            if kind == "thinking":
                if not think_started:
                    think_started = True
                    yield StreamEvent(type=Event.THINKING_START)
                thinking_buf += piece
                yield StreamEvent(type=Event.THINKING_DELTA, content=piece)
            else:
                if think_started and content_buf == "":
                    yield StreamEvent(type=Event.THINKING_END)
                    think_started = False
                content_buf += piece
                yield StreamEvent(type=Event.CONTENT_DELTA, content=piece)

        if think_started:
            yield StreamEvent(type=Event.THINKING_END)
        yield StreamEvent(type=Event.CONTENT_END)

        # 记录用量
        latency_ms = int((time.time() - start_time) * 1000)
        if self._usage_store:
            record = UsageRecord(
                provider=self.provider.label or self.provider.type,
                model=model,
                input_tokens=0,       # Ollama 不返回精确统计，放 0
                output_tokens=0,
                latency_ms=latency_ms,
                finish_reason="stop",
            )
            self._usage_store.record(record)

        yield StreamEvent(
            type=Event.COMPLETE,
            model=model,
            finish_reason="stop",
        )

    # ---- Agentic 工具调用（非流式单轮） ----

    def chat_once(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        tools: list[dict] | None = None,
        think: bool = True,
        tool_names: set[str] | None = None,
    ) -> ChatResult:
        """
        非流式单轮对话，支持工具调用。返回 ChatResult。
        用于 agent loop：模型可能返回 tool_calls，上层执行后回填再调。
        tool_names：已知工具名集合，用于文本 fallback 解析（模型不支持原生 tool_calls 时）。
        """
        if self.provider.type == "ollama":
            result = self._chat_once_ollama(model, messages, temperature, tools, think)
        else:
            result = self._chat_once_openai(model, messages, temperature, tools, think)
        # fallback：原生 tool_calls 为空但 content 里藏着工具调用
        if not result.tool_calls and tool_names and result.content:
            fallback = _extract_text_tool_calls(result.content, tool_names)
            if fallback:
                result.tool_calls = fallback
                result.content = ""
        return result

    def _chat_once_ollama(
        self, model: str, messages: list[dict],
        temperature: float, tools: list[dict] | None, think: bool,
    ) -> ChatResult:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        if think:
            payload["think"] = True
        try:
            resp = self._post("/api/chat", payload, stream=False)
            if resp.status_code == 400 and think:
                return self._chat_once_ollama(model, messages, temperature, tools, think=False)
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {})
            content = msg.get("content", "") or ""
            thinking = msg.get("thinking", "") or ""
            # content 内嵌 <think> 标签时拆分
            if "<think>" in content:
                t_extra, c_clean = "", ""
                for kind, piece in _split_think(content):
                    if kind == "thinking":
                        t_extra += piece
                    else:
                        c_clean += piece
                thinking = thinking + t_extra
                content = c_clean
            tool_calls = []
            for tc in msg.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", "") or fn.get("name", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                ))
            self._record_usage(model, data)
            return ChatResult(
                content=content, thinking=thinking, tool_calls=tool_calls,
                finish_reason=data.get("done_reason", "stop"),
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                raw_message=msg,
            )
        except requests.HTTPError:
            if think:
                return self._chat_once_ollama(model, messages, temperature, tools, think=False)
            raise

    def _chat_once_openai(
        self, model: str, messages: list[dict],
        temperature: float, tools: list[dict] | None, think: bool,
    ) -> ChatResult:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        resp = self._post("/v1/chat/completions", payload, stream=False)
        resp.raise_for_status()
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content", "") or ""
        thinking = msg.get("reasoning_content", "") or msg.get("reasoning", "") or ""
        if "<think>" in content:
            t_extra, c_clean = "", ""
            for kind, piece in _split_think(content):
                if kind == "thinking":
                    t_extra += piece
                else:
                    c_clean += piece
            thinking += t_extra
            content = c_clean
        tool_calls = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "") or ""
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args or {},
                raw_arguments=raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
            ))
        usage = data.get("usage", {})
        if self._usage_store and usage:
            self._usage_store.record(UsageRecord(
                provider=self.provider.label or self.provider.type,
                model=model,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                finish_reason=choice.get("finish_reason", "stop"),
            ))
        return ChatResult(
            content=content, thinking=thinking, tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw_message=msg,
        )

    def _record_usage(self, model: str, data: dict):
        """从 Ollama 响应记录用量"""
        if not self._usage_store:
            return
        self._usage_store.record(UsageRecord(
            provider=self.provider.label or self.provider.type,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            finish_reason=data.get("done_reason", "stop"),
        ))

    # ---- 纯提示生成 ----

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        stream: bool = True,
        think: bool = True,
    ) -> Iterator[tuple[str, str]]:
        if self.provider.type == "ollama":
            yield from self._generate_ollama(model, prompt, temperature, stream, think)
        else:
            messages = [{"role": "user", "content": prompt}]
            yield from self._chat_openai(model, messages, temperature, stream, think)

    def _generate_ollama(
        self, model: str, prompt: str,
        temperature: float, stream: bool, think: bool,
    ) -> Iterator[tuple[str, str]]:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": temperature},
        }
        if think:
            payload["think"] = True
        try:
            with self._post("/api/generate", payload, stream=stream) as resp:
                if think and resp.status_code == 400:
                    resp.close()
                    yield from self._generate_ollama(model, prompt, temperature, stream, think=False)
                    return
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        data = json.loads(line)
                        if data.get("thinking"):
                            yield ("thinking", data["thinking"])
                        resp_text = data.get("response", "")
                        if resp_text:
                            for kind, piece in _split_think(resp_text):
                                yield (kind, piece)
        except requests.HTTPError:
            if think:
                yield from self._generate_ollama(model, prompt, temperature, stream, think=False)
            else:
                raise

    # ---- 工具函数 ----

    def format_size(self, bytes_size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f} PB"
