"""工具系统 — 遵循 OpenCode 的 BaseTool 接口设计"""
from __future__ import annotations

import subprocess
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---- 工具响应 ----

@dataclass
class ToolResponse:
    """工具执行结果"""
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        if self.is_error:
            return f"[工具错误] {self.content}"
        return self.content


# ---- 工具元信息 ----

@dataclass
class ToolInfo:
    name: str
    description: str
    parameters: dict[str, Any]      # JSON Schema properties
    required: list[str] = field(default_factory=list)


# ---- 工具基类 ----

class BaseTool(ABC):
    """
    工具基类，参考 OpenCode internal/llm/tools/tools.go 设计。

    每个工具必须实现：
    - info()    — 返回工具元信息（供 AI 了解能力）
    - run(params) — 执行工具，返回 ToolResponse
    """

    @abstractmethod
    def info(self) -> ToolInfo:
        """工具元信息"""
        raise NotImplementedError

    @abstractmethod
    def run(self, params: dict) -> ToolResponse:
        """执行工具，params 为 AI 返回的参数字典"""
        raise NotImplementedError

    def _param(self, params: dict, key: str, default: Any = None) -> Any:
        return params.get(key, default)


# ---- 内置工具 ----

class GlobTool(BaseTool):
    """按模式搜索文件 (glob)"""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="glob",
            description="根据 glob 模式查找文件路径，支持 ** 递归匹配",
            parameters={
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 **/*.py 或 src/**/*.ts",
                },
                "path": {
                    "type": "string",
                    "description": "搜索根目录，默认为当前工作目录",
                },
            },
            required=["pattern"],
        )

    def run(self, params: dict) -> ToolResponse:
        import glob as _glob
        pattern = self._param(params, "pattern", "")
        root = self._param(params, "path", ".")
        if not pattern:
            return ToolResponse(content="缺少 pattern 参数", is_error=True)
        try:
            recursive = "**" in pattern
            matches = _glob.glob(pattern, root_dir=root, recursive=recursive)
            if not matches:
                return ToolResponse(content="未找到匹配文件")
            return ToolResponse(
                content="\n".join(sorted(set(matches))))
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)


class GrepTool(BaseTool):
    """在文件中搜索文本 (grep)"""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="grep",
            description="在文件中搜索包含指定文本的行，支持正则表达式",
            parameters={
                "pattern": {
                    "type": "string",
                    "description": "搜索文本或正则表达式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索目录或文件路径",
                },
                "include": {
                    "type": "string",
                    "description": "仅在匹配 glob 模式的文件中搜索，如 *.py",
                },
                "literal": {
                    "type": "boolean",
                    "description": "是否将 pattern 作为字面量（非正则）",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回多少条匹配，默认 200",
                },
            },
            required=["pattern"],
        )

    # 默认跳过的目录/扩展名（避免扫描大量无关文件）
    _SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                  ".idea", ".vscode", "dist", "build", ".mypy_cache",
                  ".pytest_cache", ".yuki-code"}
    _BINARY_EXT = {".pyc", ".exe", ".dll", ".so", ".dylib", ".zip", ".gz",
                   ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".db",
                   ".sqlite", ".woff", ".woff2", ".ttf", ".mp4", ".mp3"}

    def run(self, params: dict) -> ToolResponse:
        import fnmatch
        pattern = self._param(params, "pattern", "")
        path = self._param(params, "path", ".")
        include = self._param(params, "include", "")
        literal = self._param(params, "literal", False)
        max_results = int(self._param(params, "max_results", 200))

        if not pattern:
            return ToolResponse(content="缺少 pattern 参数", is_error=True)

        # 编译匹配器（纯 Python，跨平台）
        if literal:
            def match(line: str) -> bool:
                return pattern in line
        else:
            try:
                rx = re.compile(pattern)
            except re.error as e:
                return ToolResponse(content=f"无效正则: {e}", is_error=True)
            match = lambda line: bool(rx.search(line))

        p = Path(path)
        if not p.exists():
            return ToolResponse(content=f"路径不存在: {path}", is_error=True)

        # 收集待搜文件
        files: list[Path] = []
        if p.is_file():
            files = [p]
        else:
            for fp in p.rglob("*"):
                if not fp.is_file():
                    continue
                if any(part in self._SKIP_DIRS for part in fp.parts):
                    continue
                if fp.suffix.lower() in self._BINARY_EXT:
                    continue
                if include and not fnmatch.fnmatch(fp.name, include):
                    continue
                files.append(fp)

        results: list[str] = []
        truncated = False
        for fp in files:
            try:
                with fp.open("r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if match(line):
                            rel = fp.as_posix()
                            results.append(f"{rel}:{lineno}:{line.rstrip()}")
                            if len(results) >= max_results:
                                truncated = True
                                break
            except (OSError, UnicodeError):
                continue
            if truncated:
                break

        if not results:
            return ToolResponse(content="未找到匹配内容")
        body = "\n".join(results)
        if truncated:
            body += f"\n…(已截断，仅显示前 {max_results} 条)"
        return ToolResponse(content=body)


class ReadTool(BaseTool):
    """读取文件内容"""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="read",
            description="读取文件内容，支持 offset 和 limit 参数分段读取大文件",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "文件路径（必填）",
                },
                "offset": {
                    "type": "integer",
                    "description": "从第几行开始（从 1 计），默认 1",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取多少行，默认全部",
                },
            },
            required=["file_path"],
        )

    def run(self, params: dict) -> ToolResponse:
        path = self._param(params, "file_path", "")
        offset = int(self._param(params, "offset", 1)) - 1  # 转 0-index
        limit = self._param(params, "limit", None)

        if not path:
            return ToolResponse(content="缺少 file_path 参数", is_error=True)
        p = Path(path)
        if not p.exists():
            return ToolResponse(content=f"文件不存在: {path}", is_error=True)
        if not p.is_file():
            return ToolResponse(content=f"不是文件: {path}", is_error=True)

        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if offset >= len(lines):
                return ToolResponse(content="offset 超出文件行数")
            lines = lines[offset:]
            if limit:
                lines = lines[:int(limit)]
            content = "\n".join(lines)
            if offset > 0 or limit:
                content = f"[行 {offset+1} - {offset+len(lines)}]\n" + content
            return ToolResponse(content=content)
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)


class WriteTool(BaseTool):
    """写入文件"""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="write",
            description="创建或覆盖文件内容（危险操作，写入前请确认内容）",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "文件路径（必填）",
                },
                "content": {
                    "type": "string",
                    "description": "文件内容（必填）",
                },
            },
            required=["file_path", "content"],
        )

    def run(self, params: dict) -> ToolResponse:
        path = self._param(params, "file_path", "")
        content = self._param(params, "content", "")

        if not path:
            return ToolResponse(content="缺少 file_path 参数", is_error=True)
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResponse(content=f"已写入 {path}（{len(content)} 字符）")
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)


class EditTool(BaseTool):
    """
    精确编辑文件 — 替换 oldText 为 newText。
    比 write 更安全，只改指定片段。
    """

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="edit",
            description="替换文件中指定文本片段（oldText→newText），用于精确修改而非全文件覆盖",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "文件路径",
                },
                "old_text": {
                    "type": "string",
                    "description": "文件中必须存在的原文（必须精确匹配）",
                },
                "new_text": {
                    "type": "string",
                    "description": "替换后的内容",
                },
            },
            required=["file_path", "old_text", "new_text"],
        )

    def run(self, params: dict) -> ToolResponse:
        path = self._param(params, "file_path", "")
        old_text = self._param(params, "old_text", "")
        new_text = self._param(params, "new_text", "")

        if not path or not old_text:
            return ToolResponse(content="缺少必要参数", is_error=True)
        p = Path(path)
        if not p.exists():
            return ToolResponse(content=f"文件不存在: {path}", is_error=True)

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if old_text not in content:
                return ToolResponse(
                    content="old_text 在文件中未找到，请确认原文完全匹配",
                    is_error=True)
            new_content = content.replace(old_text, new_text, 1)
            p.write_text(new_content, encoding="utf-8")
            return ToolResponse(content=f"已修改 {path}")
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)


class BashTool(BaseTool):
    """执行 shell 命令"""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="bash",
            description="执行 shell 命令（Linux/macOS）或 PowerShell 命令（Windows）",
            parameters={
                "command": {
                    "type": "string",
                    "description": "要执行的命令",
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目录，默认为当前目录",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 30",
                },
            },
            required=["command"],
        )

    def run(self, params: dict) -> ToolResponse:
        import shutil
        command = self._param(params, "command", "")
        cwd = self._param(params, "cwd", None)
        timeout = int(self._param(params, "timeout", 30))

        if not command:
            return ToolResponse(content="缺少 command 参数", is_error=True)

        # 自动检测 shell
        shell: str | bool
        if shutil.which("bash"):
            shell = "bash"
        elif shutil.which("pwsh") or shutil.which("powershell"):
            shell = "pwsh"
        else:
            shell = True  # 系统默认

        try:
            result = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            out = []
            if result.stdout:
                out.append(result.stdout)
            if result.stderr:
                out.append(f"[stderr]\n{result.stderr}")
            if result.returncode != 0 and not out:
                out.append(f"[exit {result.returncode}]")
            body = "\n".join(out) or f"[exit {result.returncode}]"
            return ToolResponse(
                content=body,
                is_error=(result.returncode != 0),
                metadata={"exit_code": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResponse(content=f"命令超时（>{timeout}s）", is_error=True)
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)


class LsTool(BaseTool):
    """列出目录内容"""

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="ls",
            description="列出目录中的文件和子目录",
            parameters={
                "path": {
                    "type": "string",
                    "description": "目录路径，默认为当前目录",
                },
                "all": {
                    "type": "boolean",
                    "description": "是否显示隐藏文件",
                },
            },
            required=[],
        )

    def run(self, params: dict) -> ToolResponse:
        import os
        path = self._param(params, "path", ".")
        show_all = self._param(params, "all", False)

        if not Path(path).exists():
            return ToolResponse(content=f"路径不存在: {path}", is_error=True)

        try:
            names = sorted(os.listdir(path))
            if not show_all:
                names = [n for n in names if not n.startswith(".")]
            lines = []
            for name in names:
                p = Path(path) / name
                marker = "/" if p.is_dir() else ""
                size = ""
                if p.is_file():
                    try:
                        size = f"  {p.stat().st_size:>8,}"
                    except Exception:
                        pass
                lines.append(f"{size}  {name}{marker}")
            return ToolResponse(content="\n".join(lines))
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)


# ---- 工具注册表 ----

class ToolRegistry:
    """
    工具注册表 — 管理所有可用工具，提供给 AI。
    参考 OpenCode 的 tools 加载方式。
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        # 默认注册内置工具
        for cls in (GlobTool, GrepTool, ReadTool, WriteTool,
                    EditTool, BashTool, LsTool):
            self.register(cls())

    def register(self, tool: BaseTool):
        self._tools[tool.info().name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())

    def tool_infos(self) -> list[ToolInfo]:
        return [t.info() for t in self._tools.values()]

    def execute(self, name: str, params: dict) -> ToolResponse:
        tool = self._tools.get(name)
        if not tool:
            return ToolResponse(content=f"未知工具: {name}", is_error=True)
        try:
            return tool.run(params)
        except Exception as e:
            return ToolResponse(content=str(e), is_error=True)

    # ---- 构造 AI 可读的 tool_calls ----

    def to_openai_format(self) -> list[dict]:
        """转为 OpenAI function_calling 格式"""
        result = []
        for t in self._tools.values():
            info = t.info()
            result.append({
                "type": "function",
                "function": {
                    "name": info.name,
                    "description": info.description,
                    "parameters": {
                        "type": "object",
                        "properties": info.parameters,
                        "required": info.required,
                    },
                },
            })
        return result

    def to_ollama_format(self) -> list[dict]:
        """转为 Ollama tool_calling 格式（实验性）"""
        # Ollama 通过 manifest 定义 tools，这里返回简化版
        return self.to_openai_format()
