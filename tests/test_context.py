"""上下文自动感知测试"""
from cli import context as ctx


def test_discover_finds_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# 项目规范\n用中文回复", encoding="utf-8")
    found = ctx.discover_context_files(cwd=tmp_path)
    names = [str(f.path) for f in found]
    assert any("AGENTS.md" in n for n in names)


def test_discover_finds_claude_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("instructions", encoding="utf-8")
    found = ctx.discover_context_files(cwd=tmp_path)
    assert len(found) >= 1


def test_readme_not_treated_as_context(tmp_path):
    """README.md 不应被当作上下文（避免污染对话）"""
    (tmp_path / "README.md").write_text("# 项目介绍", encoding="utf-8")
    found = ctx.discover_context_files(cwd=tmp_path)
    assert all("README" not in str(f.path) for f in found)


def test_empty_dir_no_context(tmp_path):
    found = ctx.discover_context_files(cwd=tmp_path)
    assert found == []


def test_load_context_string(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("规则内容ABC", encoding="utf-8")
    text = ctx.load_context_for_directory(cwd=tmp_path)
    assert "规则内容ABC" in text


def test_load_context_empty(tmp_path):
    text = ctx.load_context_for_directory(cwd=tmp_path)
    assert text == ""


def test_summarize_contexts(tmp_path):
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    found = ctx.discover_context_files(cwd=tmp_path)
    summary = ctx.summarize_contexts(found)
    assert isinstance(summary, str)
    assert len(summary) > 0


def test_inject_into_messages(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("sys rule", encoding="utf-8")
    found = ctx.discover_context_files(cwd=tmp_path)
    msgs = ctx.inject_into_messages(found, [{"role": "user", "content": "hi"}])
    assert any(m["role"] == "system" for m in msgs)


def test_max_total_chars_limit(tmp_path):
    big = "a" * 5000
    (tmp_path / "AGENTS.md").write_text(big, encoding="utf-8")
    found = ctx.discover_context_files(cwd=tmp_path, max_total_chars=100)
    total = sum(len(f.content) for f in found)
    assert total <= 200  # 允许少量元数据余量
