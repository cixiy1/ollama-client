"""Yuki Code — AI 模型调用层，支持多 Provider"""
from __future__ import annotations

import json
import re
import requests
from dataclasses import dataclass
from typing import Iterator

from .config import Provider


@dataclass
class Model:
    name: str
    size: int = 0
    modified: str = ""
    digest: str = ""


# ---- 思考标签拆分（deepseek 等内嵌思考的模型） ----

def _split_think(text: str) -> Iterator[tuple[str, str]]:
    """将包含 <think>/</think> 标签的文本拆成 (类型, 片段) 序列。"""
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
    """

    def __init__(self, provider: Provider):
        self.provider = provider
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if provider.api_key:
            self._session.headers["Authorization"] = f"Bearer {provider.api_key}"
        if provider.extra_headers:
            self._session.headers.update(provider.extra_headers)

    # ---- 通用请求封装 ----

    def _post(self, path: str, payload: dict, stream: bool = False, timeout: int | None = None) -> requests.Response:
        url = f"{self.provider.base_url.rstrip('/')}{path}"
        t = timeout if timeout is not None else self.provider.timeout
        return self._session.post(url, json=payload, stream=stream, timeout=t)

    def _get(self, path: str, timeout: int | None = None) -> requests.Response:
        url = f"{self.provider.base_url.rstrip('/')}{path}"
        t = timeout if timeout is not None else self.provider.timeout
        return self._session.get(url, timeout=t)

    def _delete(self, path: str, payload: dict, timeout: int | None = None) -> requests.Response:
        url = f"{self.provider.base_url.rstrip('/')}{path}"
        t = timeout if timeout is not None else self.provider.timeout
        return self._session.delete(url, json=payload, timeout=t)

    # ---- 服务检测 ----

    def ping(self) -> bool:
        """检查服务是否在线"""
        try:
            r = self._get("/", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ---- 模型列表 ----

    def list_models(self) -> list[Model]:
        """列出可用模型"""
        if self.provider.type == "ollama":
            return self._list_models_ollama()
        elif self.provider.type == "openai":
            return self._list_models_openai()
        else:
            return self._list_models_openai()  # custom 默认为 OpenAI 格式

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
        """OpenAI 兼容列表，优先 /v1/models，失败则用 default_model 模拟"""
        try:
            r = self._get("/v1/models", timeout=10)
            r.raise_for_status()
            data = r.json()
            return [Model(name=m["id"]) for m in data.get("data", [])]
        except requests.RequestException:
            # 无模型列表时用 default_model 模拟一条
            if self.provider.default_model:
                return [Model(name=self.provider.default_model)]
            return []

    # ---- 模型操作（仅 Ollama 支持） ----

    def pull_model(self, name: str) -> Iterator[str]:
        """拉取模型（流式，仅 Ollama）"""
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
            yield f"[red]拉取失败: {e}[/red]"

    def delete_model(self, name: str) -> bool:
        """删除模型（仅 Ollama）"""
        if self.provider.type != "ollama":
            return False
        try:
            r = self._delete("/api/delete", {"name": name}, timeout=30)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def show_model_info(self, name: str) -> dict:
        """查看模型详情（仅 Ollama）"""
        if self.provider.type != "ollama":
            return {"error": "当前 Provider 类型不支持查看模型详情"}
        try:
            r = self._post("/api/show", {"name": name}, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    def running_models(self) -> list[dict]:
        """查看当前加载的模型（仅 Ollama）"""
        if self.provider.type != "ollama":
            return []
        try:
            r = self._get("/api/ps", timeout=10)
            r.raise_for_status()
            return r.json().get("models", [])
        except requests.RequestException:
            return []

    # ---- 对话生成 ----

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        stream: bool = True,
        think: bool = True,
    ) -> Iterator[tuple[str, str]]:
        """
        对话生成（流式），返回 (类型, 内容) 元组。
        类型为 "thinking" 或 "content"。
        """
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
        """OpenAI 兼容 /v1/chat/completions"""
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
                            line = line.decode("utf-8", errors="replace")
                            if line.startswith("data: "):
                                data_str = line[6:]
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
                                # OpenAI 格式无独立 thinking 字段
                else:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        for kind, piece in _split_think(content):
                            yield (kind, piece)
        except requests.RequestException as e:
            yield ("content", f"[请求错误: {e}]")

    # ---- 纯提示生成 ----

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        stream: bool = True,
        think: bool = True,
    ) -> Iterator[tuple[str, str]]:
        """纯提示生成（流式）"""
        if self.provider.type == "ollama":
            yield from self._generate_ollama(model, prompt, temperature, stream, think)
        else:
            # OpenAI 格式没有 /generate，用 chat 单轮模拟
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
        """字节大小转可读字符串"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f} PB"
