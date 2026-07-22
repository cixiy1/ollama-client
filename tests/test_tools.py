"""工具系统测试"""
from pathlib import Path

import pytest

from cli.tools import (
    ToolRegistry, GrepTool, GlobTool, ReadTool, WriteTool,
    EditTool, LsTool, BashTool, ToolResponse,
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text(
        "def greet(name):\n    return f'Hello {name}'\n", encoding="utf-8")
    (tmp_path / "readme.md").write_text("# Demo\ncontent here\n", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "util.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return tmp_path


def test_registry_has_builtin_tools():
    reg = ToolRegistry()
    names = {t.info().name for t in reg.list()}
    assert {"glob", "grep", "read", "write", "edit", "bash", "ls"} <= names


def test_registry_unknown_tool():
    reg = ToolRegistry()
    res = reg.execute("nope", {})
    assert res.is_error
    assert "未知工具" in res.content


def test_read_tool(sandbox):
    reg = ToolRegistry()
    res = reg.execute("read", {"file_path": str(sandbox / "hello.py")})
    assert not res.is_error
    assert "def greet" in res.content


def test_read_tool_missing(sandbox):
    reg = ToolRegistry()
    res = reg.execute("read", {"file_path": str(sandbox / "nope.py")})
    assert res.is_error


def test_read_tool_offset_limit(sandbox):
    reg = ToolRegistry()
    res = reg.execute("read", {"file_path": str(sandbox / "hello.py"),
                               "offset": 2, "limit": 1})
    assert "return" in res.content


def test_write_tool(sandbox):
    reg = ToolRegistry()
    target = sandbox / "new.txt"
    res = reg.execute("write", {"file_path": str(target), "content": "hi"})
    assert not res.is_error
    assert target.read_text(encoding="utf-8") == "hi"


def test_write_tool_creates_parent(sandbox):
    reg = ToolRegistry()
    target = sandbox / "deep" / "nested" / "f.txt"
    res = reg.execute("write", {"file_path": str(target), "content": "x"})
    assert not res.is_error
    assert target.exists()


def test_edit_tool(sandbox):
    reg = ToolRegistry()
    f = sandbox / "hello.py"
    res = reg.execute("edit", {"file_path": str(f),
                               "old_text": "Hello", "new_text": "Hi"})
    assert not res.is_error
    assert "Hi {name}" in f.read_text(encoding="utf-8")


def test_edit_tool_no_match(sandbox):
    reg = ToolRegistry()
    res = reg.execute("edit", {"file_path": str(sandbox / "hello.py"),
                               "old_text": "NOTHERE", "new_text": "x"})
    assert res.is_error


def test_grep_tool_regex(sandbox):
    reg = ToolRegistry()
    res = reg.execute("grep", {"pattern": r"def \w+", "path": str(sandbox),
                               "include": "*.py"})
    assert not res.is_error
    assert "greet" in res.content
    assert "add" in res.content


def test_grep_tool_literal(sandbox):
    reg = ToolRegistry()
    res = reg.execute("grep", {"pattern": "Hello", "path": str(sandbox),
                               "literal": True})
    assert not res.is_error
    assert "hello.py" in res.content


def test_grep_tool_no_match(sandbox):
    reg = ToolRegistry()
    res = reg.execute("grep", {"pattern": "zzzznotfound", "path": str(sandbox)})
    assert "未找到" in res.content


def test_grep_bad_regex(sandbox):
    reg = ToolRegistry()
    res = reg.execute("grep", {"pattern": "[unclosed", "path": str(sandbox)})
    assert res.is_error


def test_glob_tool(sandbox):
    reg = ToolRegistry()
    res = reg.execute("glob", {"pattern": "**/*.py", "path": str(sandbox)})
    assert not res.is_error
    assert "hello.py" in res.content
    assert "util.py" in res.content


def test_ls_tool(sandbox):
    reg = ToolRegistry()
    res = reg.execute("ls", {"path": str(sandbox)})
    assert not res.is_error
    assert "hello.py" in res.content
    assert "src/" in res.content


def test_bash_tool_echo():
    reg = ToolRegistry()
    res = reg.execute("bash", {"command": "echo yuki-test"})
    assert "yuki-test" in res.content


def test_tool_response_to_text():
    ok = ToolResponse(content="fine")
    err = ToolResponse(content="boom", is_error=True)
    assert ok.to_text() == "fine"
    assert "工具错误" in err.to_text()


def test_openai_schema_shape():
    reg = ToolRegistry()
    schema = reg.to_openai_format()
    assert all(s["type"] == "function" for s in schema)
    fn = schema[0]["function"]
    assert "name" in fn and "parameters" in fn
