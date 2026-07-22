"""API 层解析逻辑测试（无需真实模型）"""
from cli.api import (
    _extract_text_tool_calls, _split_think, ToolCall, ChatResult,
)


# ---- 文本 fallback 工具调用解析 ----

def test_bare_json_tool_call():
    r = _extract_text_tool_calls('{"name":"ls","arguments":{"path":"."}}', {"ls"})
    assert len(r) == 1
    assert r[0].name == "ls"
    assert r[0].arguments == {"path": "."}


def test_qwen_tool_call_format():
    text = '<tool_call>{"name":"read","arguments":{"file_path":"a.py"}}</tool_call>'
    r = _extract_text_tool_calls(text, {"read"})
    assert len(r) == 1
    assert r[0].name == "read"


def test_fenced_json_tool_call():
    text = '```json\n{"name":"grep","arguments":{"pattern":"def"}}\n```'
    r = _extract_text_tool_calls(text, {"grep"})
    assert len(r) == 1
    assert r[0].arguments["pattern"] == "def"


def test_unknown_tool_ignored():
    r = _extract_text_tool_calls('{"name":"danger","arguments":{}}', {"ls", "read"})
    assert r == []


def test_no_tool_names_returns_empty():
    r = _extract_text_tool_calls('{"name":"ls","arguments":{}}', set())
    assert r == []


def test_plain_text_not_parsed():
    r = _extract_text_tool_calls("这只是一段普通文字，没有工具调用", {"ls"})
    assert r == []


def test_list_of_tool_calls():
    text = '[{"name":"ls","arguments":{}}, {"name":"read","arguments":{"file_path":"x"}}]'
    r = _extract_text_tool_calls(text, {"ls", "read"})
    assert len(r) == 2


def test_arguments_as_json_string():
    text = '{"name":"ls","arguments":"{\\"path\\":\\"/tmp\\"}"}'
    r = _extract_text_tool_calls(text, {"ls"})
    assert len(r) == 1
    assert r[0].arguments == {"path": "/tmp"}


# ---- <think> 标签拆分 ----

def test_split_think_basic():
    parts = list(_split_think("<think>reasoning</think>answer"))
    assert ("thinking", "reasoning") in parts
    assert ("content", "answer") in parts


def test_split_think_no_tags():
    parts = list(_split_think("just content"))
    assert parts == [("content", "just content")]


def test_split_think_unclosed():
    parts = list(_split_think("<think>still thinking"))
    assert parts == [("thinking", "still thinking")]


def test_split_think_orphan_close():
    # 只有闭合标签时，标签被剥离，剩余作为 content
    parts = list(_split_think("leftover</think>done"))
    joined = "".join(c for _, c in parts)
    assert "done" in joined
    assert "</think>" not in joined


# ---- 数据类 ----

def test_toolcall_defaults():
    tc = ToolCall(name="ls")
    assert tc.arguments == {}
    assert tc.id == ""


def test_chatresult_defaults():
    cr = ChatResult()
    assert cr.tool_calls == []
    assert cr.content == ""
