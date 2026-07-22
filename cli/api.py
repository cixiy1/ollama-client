"""Yuki Code — AI 模型调用层"""

import requests
from typing import Iterator, Optional
from dataclasses import dataclass
import json


DEFAULT_BASE_URL = "http://localhost:11434"


def _split_think(text: str) -> Iterator[tuple[str, str]]:
    """把可能内嵌 <think>...</think> 的文本拆成 (类型, 片段) 序列。
    <think> 与 </think> 之间的归 thinking，其余（含游离的闭合标签）归 content；
    标签本身不输出。用于 deepseek 等把思考塞进 content 的模型。
    """
    while text:
        o = text.find("<think>")
        c = text.find("</think>")
        # 没有开标签：
        if o == -1:
            # 若只有游离闭合标签，直接剥掉
            if c != -1:
                text = text[:c] + text[c + len("</think>"):]
                continue
            yield ("content", text)
            return
        # 有开标签：它前面的是 content
        if o > 0:
            yield ("content", text[:o])
        after_open = text[o + len("<think>"):]
        c2 = after_open.find("</think>")
        if c2 == -1:
            # 思考未闭合，整段作为思考
            yield ("thinking", after_open)
            return
        yield ("thinking", after_open[:c2])
        text = after_open[c2 + len("</think>"):]


@dataclass
class Model:
    name: str
    size: int
    modified: str
    digest: str


class YukiAPI:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ---- 检测服务 ----

    def ping(self) -> bool:
        """检查服务是否在线"""
        try:
            r = self._session.get(f"{self.base_url}/", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ---- 模型管理 ----

    def list_models(self) -> list[Model]:
        """列出本地所有模型"""
        r = self._session.get(f"{self.base_url}/api/tags", timeout=10)
        r.raise_for_status()
        raw = r.json().get("models", [])
        return [
            Model(
                name=m["name"],
                size=m.get("size", 0),
                modified=m.get("modified_at", ""),
                digest=m.get("digest", ""),
            )
            for m in raw
        ]

    def pull_model(self, name: str) -> Iterator[str]:
        """拉取模型（流式）"""
        payload = {"name": name, "stream": True}
        with self._session.post(
            f"{self.base_url}/api/pull", json=payload, stream=True, timeout=0
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

    def delete_model(self, name: str) -> bool:
        """删除模型"""
        r = self._session.delete(
            f"{self.base_url}/api/delete", json={"name": name}, timeout=30
        )
        return r.status_code == 200

    # ---- 对话 ----

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        stream: bool = True,
        think: bool = True,
    ) -> Iterator[tuple[str, str]]:
        """
        对话生成（流式）
        messages: [{"role": "user|assistant|system", "content": "..."}]
        返回 (类型, 内容) 元组，类型为 "thinking" 或 "content"
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": temperature},
        }
        # 始终请求思考；若模型不支持 think 参数(400)，降级重试一次
        if think:
            payload["think"] = True
        try:
            with self._session.post(
                f"{self.base_url}/api/chat", json=payload, stream=stream, timeout=self.timeout
            ) as resp:
                if think and resp.status_code == 400:
                    resp.close()
                    yield from self.chat(model, messages, temperature, stream, think=False)
                    return
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        data = json.loads(line)
                        msg = data.get("message", {})
                        # 独立 thinking 字段（qwen3 等）
                        if msg.get("thinking"):
                            yield ("thinking", msg["thinking"])
                        # content 可能仍内嵌 <think> 标签（deepseek 等），在此剥离
                        content = msg.get("content", "")
                        if content:
                            for kind, piece in _split_think(content):
                                yield (kind, piece)
        except requests.HTTPError:
            if think:
                yield from self.chat(model, messages, temperature, stream, think=False)
            else:
                raise

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        stream: bool = True,
        think: bool = True,
    ) -> Iterator[tuple[str, str]]:
        """纯提示生成（流式），返回 (类型, 内容) 元组"""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": temperature},
        }
        if think:
            payload["think"] = True
        try:
            with self._session.post(
                f"{self.base_url}/api/generate", json=payload, stream=stream, timeout=self.timeout
            ) as resp:
                if think and resp.status_code == 400:
                    resp.close()
                    yield from self.generate(model, prompt, temperature, stream, think=False)
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
                yield from self.generate(model, prompt, temperature, stream, think=False)
            else:
                raise

    # ---- 系统信息 ----

    def show_model_info(self, name: str) -> dict:
        """查看模型详细信息"""
        r = self._session.post(
            f"{self.base_url}/api/show", json={"name": name}, timeout=30
        )
        r.raise_for_status()
        return r.json()

    def running_models(self) -> list[dict]:
        """查看当前加载的模型"""
        r = self._session.get(f"{self.base_url}/api/ps", timeout=10)
        r.raise_for_status()
        return r.json().get("models", [])

    def format_size(self, bytes_size: int) -> str:
        """字节大小转可读字符串"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f} PB"
