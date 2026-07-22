"""Provider 配置系统测试（隔离到 tmp 目录，不碰用户真实配置）"""
import pytest

from cli import config as c


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """把 CONFIG_DIR/CONFIG_FILE 指向临时目录"""
    d = tmp_path / ".yuki-code"
    d.mkdir()
    monkeypatch.setattr(c, "CONFIG_DIR", d)
    monkeypatch.setattr(c, "CONFIG_FILE", d / "config.json")
    yield


# ---- 工厂函数 ----

def test_ollama_factory():
    p = c.ollama()
    assert p.type == "ollama"
    assert "11434" in p.base_url


def test_openai_factory():
    p = c.openai(api_key="sk-test", default_model="gpt-4o")
    assert p.type == "openai"
    assert p.api_key == "sk-test"
    assert p.default_model == "gpt-4o"


def test_custom_factory():
    p = c.custom(name="groq", base_url="https://api.groq.com/openai/v1",
                 api_key="k")
    assert p.type == "custom"
    assert p.name == "groq"


# ---- 增删改查 ----

def test_add_and_load():
    c.add("local", c.ollama())
    cfg = c.load()
    assert "local" in cfg.providers


def test_remove():
    c.add("temp", c.ollama())
    assert c.remove("temp") is True
    cfg = c.load()
    assert "temp" not in cfg.providers


def test_remove_missing():
    assert c.remove("does-not-exist") is False


def test_rename():
    c.add("old", c.ollama())
    assert c.rename("old", "new") is True
    cfg = c.load()
    assert "new" in cfg.providers
    assert "old" not in cfg.providers


def test_use_sets_current():
    c.add("p1", c.ollama())
    c.use("p1")
    cur = c.get_current()
    assert cur is not None
    assert cur.type == "ollama"


def test_list_providers():
    c.add("a", c.ollama())
    c.add("b", c.openai(api_key="x"))
    names = {n for n, _ in c.list_providers()}
    assert {"a", "b"} <= names


def test_save_creates_backup():
    c.add("x", c.ollama())      # 首次写入
    c.add("y", c.ollama())      # 第二次应产生 .bak
    bak = c.CONFIG_FILE.with_suffix(".json.bak")
    assert bak.exists()


# ---- ConfigBuilder ----

def test_config_builder():
    b = c.ConfigBuilder()
    b.add_provider("dev", c.ollama())
    b.current("dev")
    cfg = b.build()
    assert "dev" in cfg.providers
    assert cfg.current == "dev"
