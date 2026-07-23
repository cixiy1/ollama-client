"""Provider 配置管理 — Option/Builder 模式，参考 OpenCode provider.go"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ---- 数据模型 ----

@dataclass
class Provider:
    type: str              # "ollama" | "openai" | "custom"
    name: str              # 显示名称
    base_url: str          # API 根地址
    api_key: str = ""     # API Key（可选）
    default_model: str = "" # 默认模型
    timeout: int = 120     # 请求超时（秒）
    extra_headers: dict[str, str] = field(default_factory=dict)
    disabled: bool = False  # 是否禁用
    # 用量统计用的 label
    label: str = ""

    def to_dict(self) -> dict:
        d = {
            "type": self.type,
            "name": self.name,
            "base_url": self.base_url,
            "timeout": self.timeout,
        }
        if self.api_key:
            d["api_key"] = self.api_key
        if self.default_model:
            d["default_model"] = self.default_model
        if self.extra_headers:
            d["extra_headers"] = self.extra_headers
        if self.disabled:
            d["disabled"] = True
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Provider:
        return cls(
            type=data.get("type", "custom"),
            name=data.get("name", data.get("base_url", "")),
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            default_model=data.get("default_model", ""),
            timeout=data.get("timeout", 120),
            extra_headers=data.get("extra_headers", {}),
            disabled=data.get("disabled", False),
            label=data.get("label", ""),
        )


@dataclass
class Config:
    version: int = 1
    current: str = ""      # 当前 Provider key
    providers: dict[str, Provider] = field(default_factory=dict)
    # 全局设置
    context_dir: str = ""  # 上下文文件搜索目录
    
    @property
    def default_provider(self) -> Provider | None:
        """获取当前选中的 Provider"""
        if self.current and self.current in self.providers:
            return self.providers[self.current]
        return None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "current": self.current,
            "providers": {k: v.to_dict() for k, v in self.providers.items()},
            "context_dir": self.context_dir,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        providers = {}
        for k, v in data.get("providers", {}).items():
            providers[k] = Provider.from_dict(v)
        return cls(
            version=data.get("version", 1),
            current=data.get("current", ""),
            providers=providers,
            context_dir=data.get("context_dir", ""),
        )


# ---- 配置路径 ----

CONFIG_DIR = Path.home() / ".yuki-code"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ---- 默认配置 ----

DEFAULT_CONFIG = Config(
    version=1,
    current="ollama",
    providers={
        "ollama": Provider(
            type="ollama",
            name="本地 Ollama",
            base_url=os.environ.get(
                "OLLAMA_BASE_URL", "http://localhost:11434"),
            timeout=120,
            label="ollama",
        ),
    },
)


# ---- 加载 / 保存 ----

def load() -> Config:
    """加载配置，支持环境变量覆盖"""
    if not CONFIG_FILE.exists():
        cfg = DEFAULT_CONFIG
    else:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = Config.from_dict(data)
        except (json.JSONDecodeError, OSError):
            cfg = DEFAULT_CONFIG

    # 环境变量覆盖（OLLAMA_BASE_URL 已在 Provider 中处理，
    # 这里处理全局路径）
    if os.environ.get("YUKI_CONTEXT_DIR"):
        cfg.context_dir = os.environ["YUKI_CONTEXT_DIR"]

    return cfg


def save(cfg: Config) -> None:
    """保存配置到磁盘，自动备份"""
    _ensure_dir()
    bak = CONFIG_FILE.with_suffix(".json.bak")
    if CONFIG_FILE.exists():
        shutil.copy2(CONFIG_FILE, bak)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---- Builder / Option 模式 ----

class ConfigBuilder:
    """
    配置构建器，支持链式调用。
    参考 OpenCode 的 WithXXX Option 模式。
    """
    def __init__(self):
        self._cfg = load()

    def current(self, key: str) -> "ConfigBuilder":
        self._cfg.current = key
        return self

    def add_provider(self, key: str, provider: Provider) -> "ConfigBuilder":
        self._cfg.providers[key] = provider
        return self

    def remove_provider(self, key: str) -> "ConfigBuilder":
        if key in self._cfg.providers:
            del self._cfg.providers[key]
        if self._cfg.current == key:
            self._cfg.current = next(iter(self._cfg.providers), "")
        return self

    def context_dir(self, path: str) -> "ConfigBuilder":
        self._cfg.context_dir = path
        return self

    def build(self) -> Config:
        return self._cfg

    def save(self):
        save(self._cfg)


# ---- Provider Option 函数（参考 OpenCode） ----

def WithAPIKey(key: str) -> Callable[[Provider], None]:
    """Option: 设置 API Key"""
    def apply(p: Provider):
        p.api_key = key
    return apply


def WithDefaultModel(model: str) -> Callable[[Provider], None]:
    """Option: 设置默认模型"""
    def apply(p: Provider):
        p.default_model = model
    return apply


def WithTimeout(seconds: int) -> Callable[[Provider], None]:
    """Option: 设置超时"""
    def apply(p: Provider):
        p.timeout = seconds
    return apply


def WithExtraHeaders(headers: dict[str, str]) -> Callable[[Provider], None]:
    """Option: 设置额外请求头"""
    def apply(p: Provider):
        p.extra_headers = headers
    return apply


# ---- Provider 工厂函数 ----

def ollama(base_url: str = "http://localhost:11434",
           default_model: str = "",
           timeout: int = 120) -> Provider:
    """创建 Ollama Provider"""
    return Provider(
        type="ollama",
        name="Ollama",
        base_url=base_url,
        default_model=default_model,
        timeout=timeout,
        label="ollama",
    )


def openai(base_url: str = "https://api.openai.com/v1",
           api_key: str = "",
           default_model: str = "gpt-4o-mini",
           timeout: int = 60) -> Provider:
    """创建 OpenAI Provider"""
    return Provider(
        type="openai",
        name="OpenAI",
        base_url=base_url,
        api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
        default_model=default_model,
        timeout=timeout,
        label="openai",
    )


def custom(name: str,
           base_url: str,
           api_key: str = "",
           default_model: str = "",
           timeout: int = 60,
           extra_headers: dict[str, str] | None = None) -> Provider:
    """创建 Custom Provider（兼容任意 OpenAI 兼容 API）"""
    return Provider(
        type="custom",
        name=name,
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        timeout=timeout,
        extra_headers=extra_headers or {},
        label="custom",
    )


# ---- Provider 便捷操作 ----

def get_current() -> Provider | None:
    """获取当前激活的 Provider"""
    cfg = load()
    if not cfg.current:
        return None
    return cfg.providers.get(cfg.current)


def use(name: str) -> Provider | None:
    """切换当前 Provider"""
    cfg = load()
    if name not in cfg.providers:
        return None
    cfg.current = name
    save(cfg)
    return cfg.providers[name]


def add(name: str, provider: Provider) -> None:
    """添加或更新 Provider"""
    cfg = load()
    cfg.providers[name] = provider
    if not cfg.current:
        cfg.current = name
    save(cfg)


def remove(name: str) -> bool:
    """删除 Provider"""
    cfg = load()
    if name not in cfg.providers:
        return False
    del cfg.providers[name]
    if cfg.current == name:
        cfg.current = next(iter(cfg.providers), "")
    save(cfg)
    return True


def rename(old: str, new: str) -> bool:
    """重命名 Provider"""
    cfg = load()
    if old not in cfg.providers or new in cfg.providers:
        return False
    cfg.providers[new] = cfg.providers.pop(old)
    if cfg.current == old:
        cfg.current = new
    save(cfg)
    return True


def list_providers() -> list[tuple[str, Provider]]:
    """列出所有 Provider"""
    cfg = load()
    return [(k, v) for k, v in cfg.providers.items()]
