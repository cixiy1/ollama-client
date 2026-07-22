"""Provider 配置管理"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# ---- 数据模型 ----

@dataclass
class Provider:
    type: str              # "ollama" | "openai" | "custom"
    name: str              # 显示名称
    base_url: str          # API 根地址
    api_key: str = ""      # API Key（可选）
    default_model: str = "" # 默认模型
    timeout: int = 120     # 请求超时（秒）
    extra_headers: dict[str, str] = field(default_factory=dict)  # 自定义请求头

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
        )


@dataclass
class Config:
    version: int = 1
    current: str = ""      # 当前 Provider 名称（key）
    providers: dict[str, Provider] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "current": self.current,
            "providers": {k: v.to_dict() for k, v in self.providers.items()},
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
        )


# ---- 配置文件路径 ----

CONFIG_DIR = Path.home() / ".yuki-code"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ---- 默认配置（Ollama 本地） ----

DEFAULT_CONFIG = Config(
    version=1,
    current="ollama",
    providers={
        "ollama": Provider(
            type="ollama",
            name="本地 Ollama",
            base_url="http://localhost:11434",
            timeout=120,
        ),
    },
)


# ---- 加载 / 保存 ----

def load() -> Config:
    """加载配置文件，不存在则返回默认配置（但不写入磁盘）"""
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Config.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG


def save(cfg: Config) -> None:
    """保存配置到磁盘"""
    _ensure_dir()
    bak = CONFIG_FILE.with_suffix(".json.bak")
    if CONFIG_FILE.exists():
        shutil.copy2(CONFIG_FILE, bak)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")


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
    """添加或更新一个 Provider"""
    cfg = load()
    cfg.providers[name] = provider
    if not cfg.current:
        cfg.current = name
    save(cfg)


def remove(name: str) -> bool:
    """删除 Provider，返回是否成功"""
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
    if old not in cfg.providers:
        return False
    if new in cfg.providers:
        return False
    cfg.providers[new] = cfg.providers.pop(old)
    if cfg.current == old:
        cfg.current = new
    save(cfg)
    return True
