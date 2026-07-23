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

    def run(self, params: dict, stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
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

    def run(self, params: dict, stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
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

    def run(self, params: dict, stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
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

    def run(self, params: dict, stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
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


def _make_diff(old_text: str, new_text: str, file_path: str, line_hint: int = 1) -> str:
    """生成简洁的 unified diff 预览（不超过 20 行）"""
    MAX_LINES = 20
    old_lines = old_text.rstrip("\n").split("\n")
    new_lines = new_text.rstrip("\n").split("\n")
    n_old = len(old_lines)
    n_new = len(new_lines)
    # 头部
    header = f"--- {file_path} (原始，第 {line_hint} 行起)\n+++ {file_path} (修改后)"
    # 简单行级 diff（逐行对比）
    diff_lines = [header]
    max_rows = max(n_old, n_new)
    shown = 0
    for i in range(max_rows):
        if shown >= MAX_LINES:
            diff_lines.append(f"        ... (共 {n_old}→{n_new} 行)")
            break
        lo = old_lines[i] if i < n_old else None
        ln = new_lines[i] if i < n_new else None
        if lo == ln:
            diff_lines.append(f"  {lo}")
        else:
            if lo is not None:
                diff_lines.append(f"- {lo}")
                shown += 1
            if ln is not None:
                diff_lines.append(f"+ {ln}")
                shown += 1
        shown += 1
    return "\n".join(diff_lines)


class EditTool(BaseTool):
    """
    编辑文件 — 支持两种模式：
    1. old_line（行号）模式：替换指定行，不依赖字符串匹配
    2. old_text（字符串）模式：精确替换原文片段（原有行为）
    两种模式二选一，old_line 优先。
    """

    def info(self) -> ToolInfo:
        return ToolInfo(
            name="edit",
            description=("编辑文件，支持两种模式（old_line 优先）：\n"
                        "- old_line 模式：按行号替换（推荐），格式：\"3\"（单行）\"3-7\"（范围）\"3+\"（第3行到末尾）\n"
                        "- old_text 模式：精确匹配字符串片段（原有行为）"),
            parameters={
                "file_path": {"type": "string", "description": "文件路径"},
                "old_line": {
                    "type": "string",
                    "description": ("行号或范围（优先于 old_text）：\n"
                                   "  \"3\"     → 替换第 3 行\n"
                                   "  \"3-7\"   → 替换第 3 到 7 行\n"
                                   "  \"3+\"    → 替换第 3 行到文件末尾\n"
                                   "  \"-5\"    → 替换倒数第 5 行到末尾\n"
                                   "  \"3-7 new line8\" → 同时替换+插入（中间空格为新行）")},
                "new_text": {"type": "string", "description": "替换后的内容（含换行时用 \\n）"},
                "old_text": {
                    "type": "string",
                    "description": "精确匹配要替换的原文片段（old_line 未提供时使用）"},
            },
            required=["file_path", "new_text"],
        )

    def run(self, params: dict, stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
        path = self._param(params, "file_path", "")
        old_line = self._param(params, "old_line", "").strip()
        old_text = self._param(params, "old_text", "")
        new_text = self._param(params, "new_text", "")

        if not path:
            return ToolResponse(content="缺少 file_path", is_error=True)
        p = Path(path)
        if not p.exists():
            return ToolResponse(content=f"文件不存在: {path}", is_error=True)

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            # 去除 splitlines 产生的尾部空串（处理文件末尾 \n）
            has_trailing_nl = content.endswith("\n")
            lines = content.rstrip("\n").split("\n") if content else []
            n = len(lines)

            if old_line:
                # ---- 行号模式 ----
                # 解析 old_line：支持 "3" "3-7" "3+" "-3"
                # new_text_expanded: 支持 \\n 转义，并去掉末尾多余空行
                new_text_expanded = new_text.replace(r"\n", "\n")
                # splitlines 避免 "text\n".split("\n") 产生尾部空串的问题
                new_text_parts = new_text_expanded.splitlines()

                def parse_idx(s: str) -> int:
                    """解析单个索引，支持负数（从末尾）"""
                    s = s.strip()
                    neg = s.startswith("-")
                    s = s.lstrip("-+")
                    idx = int(s) - 1  # 转 0-index
                    if neg:
                        idx = n + idx  # -1 → n-1（末尾）
                    else:
                        idx = max(0, idx)
                    return idx

                if "-" in old_line and not old_line.startswith("-"):
                    # "3-7" 范围
                    parts = old_line.split("-", 1)
                    start = parse_idx(parts[0])
                    end_raw = parts[1].strip()
                    if not end_raw:
                        end = n - 1
                    elif end_raw.endswith("+"):
                        end = n - 1
                    else:
                        end = parse_idx(end_raw)
                    end = min(end, n - 1)
                    if start > end:
                        return ToolResponse(
                            content=f"起始行 {start+1} 大于结束行 {end+1}",
                            is_error=True)
                    removed = "\n".join(lines[start:end + 1])
                    new_lines = lines[:start] + new_text_parts + lines[end + 1:]
                elif old_line.endswith("+"):
                    # "3+" 从第3行到末尾
                    start = parse_idx(old_line.rstrip("+"))
                    removed = "\n".join(lines[start:])
                    new_lines = lines[:start] + new_text_parts
                elif old_line.startswith("-") and "-" in old_line[1:]:
                    # "-3" 倒数第3行到末尾
                    start = parse_idx(old_line)
                    removed = "\n".join(lines[start:])
                    new_lines = lines[:start] + new_text_parts
                else:
                    # "3" 单行
                    start = parse_idx(old_line)
                    removed = lines[start]
                    new_lines = lines[:start] + new_text_parts + lines[start + 1:]

                # 确定 diff 头部行号（1-indexed）
                # 单行 "3" / 范围 "3-7" / 后缀 "3+": 行号为 start+1
                # 负索引 "-3": 用 parse_idx(-3) 即 n-3+1 = n-2（1-indexed）
                diff_line = start + 1  # 默认正确（单行/范围/+）
                if old_line.startswith("-"):
                    diff_line = parse_idx(old_line) + 1
                diff_preview = _make_diff(removed, new_text_expanded,
                                          path, diff_line)
                new_content = "\n".join(new_lines)
                if has_trailing_nl:
                    new_content += "\n"
                p.write_text(new_content, encoding="utf-8")
                return ToolResponse(
                    content=f"已替换 {path} 行 {old_line}\n\n{diff_preview}")

            elif old_text:
                # ---- 字符串模式（原有行为） ----
                if old_text not in content:
                    return ToolResponse(
                        content="old_text 在文件中未找到，请确认原文完全匹配",
                        is_error=True)
                new_content = content.replace(old_text, new_text, 1)
                p.write_text(new_content, encoding="utf-8")
                return ToolResponse(content=f"已修改 {path}")

            else:
                return ToolResponse(
                    content="必须提供 old_line（行号）或 old_text（字符串）之一",
                    is_error=True)

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

    def run(self, params: dict,
             stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
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
            # 流式模式：实时输出命令行的每一行
            if stream_cb:
                proc = subprocess.Popen(
                    command, shell=shell, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, cwd=cwd,
                    text=True, errors="replace",
                )
                out_buf: list[str] = []
                # 实时读 stdout/stderr（分开读取避免死锁）
                import select as _select
                import time as _time
                deadline = _time.monotonic() + timeout
                while True:
                    remaining = max(deadline - _time.monotonic(), 0.1)
                    # 非 Windows 用 select，Windows 退化到缓冲读
                    rdy = []
                    if proc.stdout:
                        if hasattr(_select, "select"):
                            rdy, _, _ = _select.select([proc.stdout], [], [], min(0.5, remaining))
                        else:
                            rdy = [proc.stdout]
                    if proc.stderr:
                        # Windows select 不支持管道，这里跳过 stderr 实时流，只在结束时读
                        pass
                    if rdy:
                        line = proc.stdout.readline()
                        if line:
                            out_buf.append(line)
                            stream_cb(line)
                        elif proc.poll() is not None:
                            break
                    if proc.poll() is not None:
                        break
                    if _time.monotonic() >= deadline:
                        proc.kill()
                        stream_cb("\n[超时 killed]")
                        break
                    _time.sleep(0.01)
                # 结束时读剩余 stderr
                if proc.stderr:
                    stderr_rem = proc.stderr.read()
                    if stderr_rem:
                        stream_cb(f"\n[stderr]\n{stderr_rem}")
                exit_code = proc.wait()
                body = "".join(out_buf) or f"[exit {exit_code}]"
                return ToolResponse(
                    content=body,
                    is_error=(exit_code != 0),
                    metadata={"exit_code": exit_code},
                )
            else:
                # 非流式（原有行为）
                result = subprocess.run(
                    command, shell=shell, capture_output=True,
                    text=True, timeout=timeout, cwd=cwd,
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

    def run(self, params: dict, stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
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


# ---- Git 工具 ----

class GitTool(BaseTool):
    """Git 操作工具：status / diff / log / branch / checkout / commit"""

    def info(self) -> ToolInfo:
        desc = (
            "执行 Git 操作。子命令：" +
            "status [path]    - 当前状态（默认当前目录）" +
            "diff [path]      - 查看未暂存的变更" +
            "diff --cached    - 查看已暂存的变更" +
            "log [-n N]       - 最近 N 条提交记录（默认 5）" +
            "branch           - 列出所有分支" +
            "branch -r        - 列出远程分支" +
            "checkout <branch> - 切换分支" +
            "add <path>       - 暂存文件（path 为空则全暂存）" +
            "commit -m <msg>  - 提交，消息必需" +
            "push             - 推送到远程" +
            "pull             - 从远程拉取" +
            "示例: git status / git diff src/main.py / git commit -m fix:bug"
        )
        cmd_desc = (
            "Git 子命令，如 status, diff, log, branch, checkout, add, commit, push, pull。"
            "格式：子命令 [参数...]，如 diff --cached 或 log -n 10。"
        )
        return ToolInfo(
            name="git",
            description=desc,
            parameters={
                "command": {
                    "type": "string",
                    "description": cmd_desc,
                },
                "cwd": {
                    "type": "string",
                    "description": "执行 git 命令的目录，默认为当前工作目录",
                },
            },
            required=["command"],
        )

    def run(self, params: dict,
            stream_cb: "callable[[str], None] | None" = None) -> ToolResponse:
        cmd_str = self._param(params, "command", "status")
        cwd = self._param(params, "cwd")

        parts = cmd_str.strip().split()
        if not parts:
            return ToolResponse(content="git: 子命令不能为空", is_error=True)

        git_cmd = ["git"] + parts

        if "-m" in parts:
            idx = parts.index("-m")
            if idx + 1 < len(parts):
                msg = parts[idx + 1]
                git_cmd = ["git"] + parts[:idx] + ["-m", msg]

        try:
            result = subprocess.run(
                git_cmd,
                capture_output=True, text=True,
                cwd=cwd or None,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return ToolResponse(content="git: 命令执行超时（60s）", is_error=True)
        except FileNotFoundError:
            return ToolResponse(
                content="git: 未找到 git 命令，请确认已安装 Git 并在 PATH 中",
                is_error=True,
            )

        out = result.stdout
        err = result.stderr

        if result.returncode != 0 and err:
            out = (out + "\n" + err).strip() if out else err.strip()
            return ToolResponse(content=out, is_error=True)

        if stream_cb and out:
            stream_cb(out)

        return ToolResponse(content=out or "(无输出)")

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
                    EditTool, BashTool, LsTool, GitTool):
            self.register(cls())

    def register(self, tool: BaseTool):
        self._tools[tool.info().name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        return list(self._tools.values())

    def tool_infos(self) -> list[ToolInfo]:
        return [t.info() for t in self._tools.values()]

    def execute(self, name: str, params: dict,
                stream_cb: "Callable[[str], None] | None" = None) -> ToolResponse:
        tool = self._tools.get(name)
        if not tool:
            return ToolResponse(content=f"未知工具: {name}", is_error=True)
        try:
            return tool.run(params, stream_cb=stream_cb)
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
