"""快捷键系统 — 支持键盘快捷键"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Union
from enum import Enum


class KeyModifier(Enum):
    """按键修饰符"""
    CTRL = "ctrl"
    ALT = "alt"
    SHIFT = "shift"
    META = "meta"


@dataclass
class KeyboardShortcut:
    """快捷键定义"""
    name: str
    description: str
    keys: List[str]  # 如 ["ctrl", "c"]
    action: Callable  # 执行的函数
    enabled: bool = True
    category: str = "general"  # 分类：general, chat, tools, etc.
    
    def to_key_string(self) -> str:
        """转换为按键字符串"""
        return "+".join(self.keys)
    
    def matches(self, pressed_keys: List[str]) -> bool:
        """检查是否匹配按键"""
        if len(self.keys) != len(pressed_keys):
            return False
        
        # 检查每个键是否匹配（忽略大小写）
        for key1, key2 in zip(self.keys, pressed_keys):
            if key1.lower() != key2.lower():
                return False
        
        return True


@dataclass
class ShortcutConfig:
    """快捷键配置"""
    shortcuts: Dict[str, KeyboardShortcut] = field(default_factory=dict)
    disabled_categories: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """初始化默认快捷键"""
        if not self.shortcuts:
            self._create_default_shortcuts()
    
    def _create_default_shortcuts(self):
        """创建默认快捷键"""
        # 通用快捷键
        self.shortcuts.update({
            "exit": KeyboardShortcut(
                name="exit",
                description="退出程序",
                keys=["ctrl", "q"],
                action=lambda: "exit",
                category="general"
            ),
            "help": KeyboardShortcut(
                name="help",
                description="显示帮助",
                keys=["ctrl", "h"],
                action=lambda: "help",
                category="general"
            ),
            "clear": KeyboardShortcut(
                name="clear",
                description="清屏",
                keys=["ctrl", "l"],
                action=lambda: "clear",
                category="general"
            ),
            "status": KeyboardShortcut(
                name="status",
                description="显示状态",
                keys=["ctrl", "s"],
                action=lambda: "status",
                category="general"
            ),
        })
        
        # 聊天快捷键
        self.shortcuts.update({
            "send": KeyboardShortcut(
                name="send",
                description="发送消息",
                keys=["enter"],
                action=lambda: "send",
                category="chat"
            ),
            "cancel": KeyboardShortcut(
                name="cancel",
                description="取消当前操作",
                keys=["ctrl", "c"],
                action=lambda: "cancel",
                category="chat"
            ),
            "retry": KeyboardShortcut(
                name="retry",
                description="重试上一次对话",
                keys=["ctrl", "r"],
                action=lambda: "retry",
                category="chat"
            ),
            "undo": KeyboardShortcut(
                name="undo",
                description="撤销最后一轮对话",
                keys=["ctrl", "z"],
                action=lambda: "undo",
                category="chat"
            ),
        })
        
        # 工具快捷键
        self.shortcuts.update({
            "tools": KeyboardShortcut(
                name="tools",
                description="显示工具列表",
                keys=["ctrl", "t"],
                action=lambda: "tools",
                category="tools"
            ),
            "config": KeyboardShortcut(
                name="config",
                description="打开配置",
                keys=["ctrl", ","],
                action=lambda: "config",
                category="tools"
            ),
            "theme": KeyboardShortcut(
                name="theme",
                description="切换主题",
                keys=["ctrl", "t"],
                action=lambda: "theme",
                category="tools"
            ),
        })
    
    def get_shortcut(self, name: str) -> Optional[KeyboardShortcut]:
        """获取快捷键"""
        return self.shortcuts.get(name)
    
    def add_shortcut(self, shortcut: KeyboardShortcut) -> bool:
        """添加快捷键"""
        try:
            self.shortcuts[shortcut.name] = shortcut
            return True
        except Exception:
            return False
    
    def remove_shortcut(self, name: str) -> bool:
        """删除快捷键"""
        if name in self.shortcuts:
            del self.shortcuts[name]
            return True
        return False
    
    def list_shortcuts(self, category: str = None) -> List[KeyboardShortcut]:
        """列出快捷键"""
        shortcuts = list(self.shortcuts.values())
        
        if category:
            shortcuts = [s for s in shortcuts if s.category == category]
        
        return shortcuts
    
    def find_shortcut_by_keys(self, pressed_keys: List[str]) -> Optional[KeyboardShortcut]:
        """根据按键查找快捷键"""
        for shortcut in self.shortcuts.values():
            if shortcut.enabled and shortcut.matches(pressed_keys):
                return shortcut
        return None
    
    def enable_category(self, category: str):
        """启用分类"""
        if category not in self.disabled_categories:
            self.disabled_categories.remove(category)
    
    def disable_category(self, category: str):
        """禁用分类"""
        if category not in self.disabled_categories:
            self.disabled_categories.append(category)
    
    def is_category_enabled(self, category: str) -> bool:
        """检查分类是否启用"""
        return category not in self.disabled_categories


class KeyboardManager:
    """快捷键管理器"""
    
    def __init__(self, config_file: str | Path = None):
        self.config_file = Path(config_file) if config_file else Path.home() / ".yuki-code" / "shortcuts.json"
        self.config_dir = self.config_file.parent
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._config = self._load_config()
        self._key_pressed = []
        self._key_handlers: Dict[str, Callable] = {}
    
    def _load_config(self) -> ShortcutConfig:
        """加载快捷键配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return ShortcutConfig(**data)
            except Exception:
                pass
        
        return ShortcutConfig()
    
    def _save_config(self):
        """保存快捷键配置"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(self._config), f, indent=2, ensure_ascii=False)
    
    def add_key_handler(self, key_name: str, handler: Callable):
        """添加按键处理器"""
        self._key_handlers[key_name] = handler
    
    def on_key_press(self, key: str):
        """处理按键按下"""
        self._key_pressed.append(key.lower())
        
        # 查找匹配的快捷键
        shortcut = self._config.find_shortcut_by_keys(self._key_pressed)
        
        if shortcut:
            # 执行快捷键动作
            result = shortcut.action()
            
            # 如果有对应的处理器，调用它
            if result in self._key_handlers:
                self._key_handlers[result]()
    
    def on_key_release(self, key: str):
        """处理按键释放"""
        key = key.lower()
        if key in self._key_pressed:
            self._key_pressed.remove(key)
    
    def get_shortcut(self, name: str) -> Optional[KeyboardShortcut]:
        """获取快捷键"""
        return self._config.get_shortcut(name)
    
    def add_shortcut(self, shortcut: KeyboardShortcut) -> bool:
        """添加快捷键"""
        success = self._config.add_shortcut(shortcut)
        if success:
            self._save_config()
        return success
    
    def remove_shortcut(self, name: str) -> bool:
        """删除快捷键"""
        success = self._config.remove_shortcut(name)
        if success:
            self._save_config()
        return success
    
    def list_shortcuts(self, category: str = None) -> List[KeyboardShortcut]:
        """列出快捷键"""
        return self._config.list_shortcuts(category)
    
    def enable_category(self, category: str):
        """启用分类"""
        self._config.enable_category(category)
        self._save_config()
    
    def disable_category(self, category: str):
        """禁用分类"""
        self._config.disable_category(category)
        self._save_config()
    
    def get_help_text(self, category: str = None) -> str:
        """获取帮助文本"""
        shortcuts = self.list_shortcuts(category)
        
        if not shortcuts:
            return "没有可用的快捷键"
        
        help_lines = []
        help_lines.append("快捷键帮助:")
        help_lines.append("=" * 40)
        
        for shortcut in shortcuts:
            key_str = shortcut.to_key_string()
            help_lines.append(f"{key_str:<15} {shortcut.description}")
        
        return "\n".join(help_lines)
    
    def create_custom_shortcut(self, name: str, description: str, keys: List[str], 
                             action: Callable, category: str = "custom") -> bool:
        """创建自定义快捷键"""
        shortcut = KeyboardShortcut(
            name=name,
            description=description,
            keys=keys,
            action=action,
            category=category
        )
        
        return self.add_shortcut(shortcut)
    
    def bind_action_to_shortcut(self, shortcut_name: str, action: Callable) -> bool:
        """为快捷键绑定动作"""
        shortcut = self.get_shortcut(shortcut_name)
        if shortcut:
            shortcut.action = action
            self._save_config()
            return True
        return False
    
    def get_shortcut_stats(self) -> Dict[str, Any]:
        """获取快捷键统计"""
        total = len(self._config.shortcuts)
        enabled = sum(1 for s in self._config.shortcuts.values() if s.enabled)
        
        categories = {}
        for shortcut in self._config.shortcuts.values():
            if shortcut.category not in categories:
                categories[shortcut.category] = 0
            categories[shortcut.category] += 1
        
        return {
            "total_shortcuts": total,
            "enabled_shortcuts": enabled,
            "disabled_categories": self._config.disabled_categories,
            "categories": categories
        }