"""会话 / 用量存储测试"""
import pytest

from cli.session import SessionStore, Message
from cli.usage import UsageStore, UsageRecord, estimate_cost


# ---- SessionStore ----

@pytest.fixture
def store(tmp_path):
    return SessionStore(db_path=tmp_path / "sessions.db")


def test_create_and_get_session(store):
    s = store.create_session(provider="ollama", model="qwen3:8b")
    got = store.get_session(s.id)
    assert got is not None
    assert got.model == "qwen3:8b"


def test_add_message(store):
    s = store.create_session(provider="ollama", model="m")
    store.add_message(s.id, Message(role="user", content="hi"))
    store.add_message(s.id, Message(role="assistant", content="hello"))
    got = store.get_session(s.id)
    assert len(got.messages) == 2
    assert got.messages[0].content == "hi"


def test_sanitize_surrogate(store):
    """孤立代理对不应导致 SQLite 崩溃"""
    s = store.create_session(provider="ollama", model="m")
    bad = "normal \ud83d text"  # 孤立的高代理
    store.add_message(s.id, Message(role="user", content=bad))
    got = store.get_session(s.id)
    assert got is not None
    assert len(got.messages) == 1


def test_list_sessions(store):
    store.create_session(provider="ollama", model="a")
    store.create_session(provider="ollama", model="b")
    sessions = store.list_sessions()
    assert len(sessions) >= 2


def test_auto_title(store):
    s = store.create_session(provider="ollama", model="m")
    store.add_message(s.id, Message(role="user", content="帮我写一个快速排序算法"))
    store.auto_title(s.id)
    got = store.get_session(s.id)
    assert got.title != "新对话"
    assert len(got.title) > 0


def test_delete_session(store):
    s = store.create_session(provider="ollama", model="m")
    store.delete_session(s.id)
    assert store.get_session(s.id) is None


# ---- UsageStore ----

@pytest.fixture
def usage(tmp_path):
    return UsageStore(db_path=tmp_path / "usage.db")


def test_record_and_summary(usage):
    usage.record(UsageRecord(provider="ollama", model="m",
                             input_tokens=100, output_tokens=50))
    usage.record(UsageRecord(provider="ollama", model="m",
                             input_tokens=200, output_tokens=80))
    summ = usage.summary()
    assert summ["input_tokens"] == 300
    assert summ["output_tokens"] == 130
    assert summ["requests"] == 2


def test_recent(usage):
    usage.record(UsageRecord(provider="ollama", model="m",
                             input_tokens=1, output_tokens=1))
    recent = usage.recent(limit=5)
    assert len(recent) == 1
    assert recent[0].model == "m"


def test_usage_record_total():
    r = UsageRecord(provider="p", model="m", input_tokens=10, output_tokens=5)
    assert r.total_tokens == 15


def test_estimate_cost_unknown_model_zero():
    # 未知模型（本地 Ollama）成本应为 0
    assert estimate_cost("some-local-model", 1000, 1000) == 0.0


def test_summary_empty(usage):
    summ = usage.summary()
    assert summ["input_tokens"] == 0
    assert summ["output_tokens"] == 0
