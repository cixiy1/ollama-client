"""主题定制系统 — 支持深色/浅色主题切换、颜色配置"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional, Any


@dataclass
class Theme:
    """主题配置"""
    name: str = "default"
    type: str = "light"  # "light" | "dark"
    
    # 主要颜色
    primary_color: str = "#007acc"
    secondary_color: str = "#6c757d"
    success_color: str = "#28a745"
    warning_color: str = "#ffc107"
    error_color: str = "#dc3545"
    
    # 背景色
    background_color: str = "#ffffff"
    surface_color: str = "#f8f9fa"
    card_color: str = "#ffffff"
    
    # 文字颜色
    text_primary: str = "#212529"
    text_secondary: str = "#6c757d"
    text_disabled: str = "#adb5bd"
    
    # 边框和分割线
    border_color: str = "#dee2e6"
    divider_color: str = "#e9ecef"
    
    # 思考和回答颜色
    thinking_bg: str = "#fff3cd"
    thinking_border: str = "#ffeaa7"
    thinking_text: str = "#856404"
    
    answer_bg: str = "#d4edda"
    answer_border: str = "#c3e6cb"
    answer_text: str = "#155724"
    
    # 状态指示器
    spinner_color: str = "#007acc"
    progress_color: str = "#007acc"
    
    def to_rich_styles(self) -> Dict[str, Any]:
        """转换为 Rich 样式"""
        return {
            # 主要颜色
            "primary": self.primary_color,
            "secondary": self.secondary_color,
            "success": self.success_color,
            "warning": self.warning_color,
            "error": self.error_color,
            
            # 背景色
            "background": self.background_color,
            "surface": self.surface_color,
            "card": self.card_color,
            
            # 文字颜色
            "text_primary": self.text_primary,
            "text_secondary": self.text_secondary,
            "text_disabled": self.text_disabled,
            
            # 边框和分割线
            "border": self.border_color,
            "divider": self.divider_color,
            
            # 思考和回答颜色
            "thinking_bg": self.thinking_bg,
            "thinking_border": self.thinking_border,
            "thinking_text": self.thinking_text,
            "answer_bg": self.answer_bg,
            "answer_border": self.answer_border,
            "answer_text": self.answer_text,
            
            # 状态指示器
            "spinner": self.spinner_color,
            "progress": self.progress_color,
        }


@dataclass
class ThemeConfig:
    """主题配置管理"""
    current_theme: str = "default"
    themes: Dict[str, Theme] = field(default_factory=dict)
    
    def __post_init__(self):
        """初始化默认主题"""
        if not self.themes:
            self._create_default_themes()
    
    def _create_default_themes(self):
        """创建默认主题"""
        # 浅色主题
        light_theme = Theme(
            name="light",
            type="light",
            background_color="#ffffff",
            surface_color="#f8f9fa",
            card_color="#ffffff",
            text_primary="#212529",
            text_secondary="#6c757d",
            border_color="#dee2e6",
            divider_color="#e9ecef",
            thinking_bg="#fff3cd",
            thinking_border="#ffeaa7",
            thinking_text="#856404",
            answer_bg="#d4edda",
            answer_border="#c3e6cb",
            answer_text="#155724"
        )
        
        # 深色主题
        dark_theme = Theme(
            name="dark",
            type="dark",
            background_color="#1a1a1a",
            surface_color="#2d2d2d",
            card_color="#363636",
            text_primary="#ffffff",
            text_secondary="#b0b0b0",
            border_color="#404040",
            divider_color="#4a4a4a",
            thinking_bg="#3d3d00",
            thinking_border="#4d4d00",
            thinking_text="#ffff99",
            answer_bg="#003d3d",
            answer_border="#004d4d",
            answer_text="#99ffcc"
        )
        
        # 蓝色主题
        blue_theme = Theme(
            name="blue",
            type="light",
            primary_color="#0066cc",
            secondary_color="#4d94ff",
            background_color="#f0f8ff",
            surface_color="#e6f2ff",
            card_color="#ffffff",
            text_primary="#003366",
            text_secondary="#0066cc",
            border_color="#b3d9ff",
            divider_color="#cce6ff",
            thinking_bg="#e6f3ff",
            thinking_border="#cce7ff",
            thinking_text="#0066cc",
            answer_bg="#cce7ff",
            answer_border="#99d6ff",
            answer_text="#003d7a"
        )
        
        self.themes = {
            "default": light_theme,
            "light": light_theme,
            "dark": dark_theme,
            "blue": blue_theme
        }
    
    def get_current_theme(self) -> Theme:
        """获取当前主题"""
        return self.themes.get(self.current_theme, self.themes["default"])
    
    def set_theme(self, theme_name: str) -> bool:
        """设置主题"""
        if theme_name in self.themes:
            self.current_theme = theme_name
            return True
        return False
    
    def add_theme(self, theme: Theme) -> bool:
        """添加自定义主题"""
        try:
            self.themes[theme.name] = theme
            return True
        except Exception:
            return False
    
    def remove_theme(self, theme_name: str) -> bool:
        """删除主题"""
        if theme_name in self.themes and theme_name not in ["default", "light", "dark"]:
            del self.themes[theme_name]
            return True
        return False
    
    def list_themes(self) -> list[str]:
        """列出所有主题"""
        return list(self.themes.keys())
    
    def get_theme_info(self, theme_name: str) -> Optional[Dict[str, Any]]:
        """获取主题信息"""
        theme = self.themes.get(theme_name)
        if theme:
            return asdict(theme)
        return None


class ThemeManager:
    """主题管理器"""
    
    def __init__(self, config_file: str | Path = None):
        self.config_file = Path(config_file) if config_file else Path.home() / ".yuki-code" / "themes.json"
        self.config_dir = self.config_file.parent
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._config = self._load_config()
    
    def _load_config(self) -> ThemeConfig:
        """加载主题配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return ThemeConfig(**data)
            except Exception:
                pass
        
        return ThemeConfig()
    
    def _save_config(self):
        """保存主题配置"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(self._config), f, indent=2, ensure_ascii=False)
    
    def get_current_theme(self) -> Theme:
        """获取当前主题"""
        return self._config.get_current_theme()
    
    def set_theme(self, theme_name: str) -> bool:
        """设置主题"""
        success = self._config.set_theme(theme_name)
        if success:
            self._save_config()
        return success
    
    def add_theme(self, theme: Theme) -> bool:
        """添加自定义主题"""
        success = self._config.add_theme(theme)
        if success:
            self._save_config()
        return success
    
    def remove_theme(self, theme_name: str) -> bool:
        """删除主题"""
        success = self._config.remove_theme(theme_name)
        if success:
            self._save_config()
        return success
    
    def list_themes(self) -> list[str]:
        """列出所有主题"""
        return self._config.list_themes()
    
    def get_theme_info(self, theme_name: str) -> Optional[Dict[str, Any]]:
        """获取主题信息"""
        return self._config.get_theme_info(theme_name)
    
    def apply_theme_to_rich(self, console) -> Dict[str, Any]:
        """应用主题到 Rich 控制台"""
        theme = self.get_current_theme()
        styles = theme.to_rich_styles()
        
        # 这里可以扩展为实际设置 Rich 样式
        # 由于 Rich 的样式系统比较复杂，这里返回样式字典供使用
        
        return styles
    
    def create_theme_from_colors(self, name: str, colors: Dict[str, str]) -> Theme:
        """从颜色创建主题"""
        theme = Theme(name=name)
        
        # 更新颜色
        for key, value in colors.items():
            if hasattr(theme, key):
                setattr(theme, key, value)
        
        return theme