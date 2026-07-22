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
