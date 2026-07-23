"""配置文件管理 — 支持配置文件导入/导出、配置模板"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import asdict

from .config import Config, Provider


class ConfigManager:
    """配置文件管理器"""
    
    def __init__(self, config_file: str | Path = None):
        self.config_file = Path(config_file) if config_file else Path.home() / ".yuki-code" / "config.json"
        self.config_dir = self.config_file.parent
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
    def export_config(self, output_file: str | Path, include_sensitive: bool = False) -> bool:
        """导出配置文件
        
        Args:
            output_file: 输出文件路径
            include_sensitive: 是否包含敏感信息（API Key等）
            
        Returns:
            bool: 是否成功
        """
        try:
            config = Config.from_dict(self._load_config_dict())
            
            if not include_sensitive:
                # 清理敏感信息
                for provider in config.providers.values():
                    provider.api_key = ""
                    provider.extra_headers = {}
                    
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(config), f, indent=2, ensure_ascii=False)
                
            return True
            
        except Exception as e:
            print(f"导出配置失败: {e}")
            return False
    
    def import_config(self, input_file: str | Path) -> bool:
        """导入配置文件
        
        Args:
            input_file: 输入文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            input_path = Path(input_file)
            if not input_path.exists():
                print(f"配置文件不存在: {input_file}")
                return False
                
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            config = Config.from_dict(data)
            
            # 验证配置
            if not self._validate_config(config):
                print("配置文件验证失败")
                return False
                
            # 保存配置
            self._save_config(config)
            return True
            
        except Exception as e:
            print(f"导入配置失败: {e}")
            return False
    
    def get_config_template(self, provider_type: str = "ollama") -> Dict[str, Any]:
        """获取配置模板
        
        Args:
            provider_type: Provider 类型
            
        Returns:
            Dict: 配置模板
        """
        templates = {
            "ollama": {
                "type": "ollama",
                "name": "Ollama Local",
                "base_url": "http://localhost:11434",
                "api_key": "",
                "default_model": "qwen2.5:7b",
                "timeout": 120,
                "extra_headers": {},
                "disabled": False,
                "label": "ollama-local"
            },
            "openai": {
                "type": "openai",
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-your-api-key-here",
                "default_model": "gpt-4",
                "timeout": 120,
                "extra_headers": {},
                "disabled": False,
                "label": "openai"
            },
            "custom": {
                "type": "custom",
                "name": "Custom API",
                "base_url": "https://api.example.com/v1",
                "api_key": "your-api-key-here",
                "default_model": "custom-model",
                "timeout": 120,
                "extra_headers": {},
                "disabled": False,
                "label": "custom-api"
            }
        }
        
        return templates.get(provider_type, templates["ollama"])
    
    def list_templates(self) -> List[str]:
        """列出所有可用的配置模板
        
        Returns:
            List[str]: 模板名称列表
        """
        return ["ollama", "openai", "custom"]
    
    def create_from_template(self, provider_type: str, name: str = None) -> bool:
        """从模板创建配置
        
        Args:
            provider_type: Provider 类型
            name: 自定义名称
            
        Returns:
            bool: 是否成功
        """
        try:
            template = self.get_config_template(provider_type)
            
            if name:
                template["name"] = name
                
            config = self.load()
            key = template["label"]
            config.providers[key] = Provider(**template)
            
            if not config.current:
                config.current = key
                
            self.save(config)
            return True
            
        except Exception as e:
            print(f"从模板创建配置失败: {e}")
            return False
    
    def backup_config(self) -> bool:
        """备份当前配置
        
        Returns:
            bool: 是否成功
        """
        try:
            if not self.config_file.exists():
                return False
                
            backup_file = self.config_file.with_suffix(".backup.json")
            shutil.copy2(self.config_file, backup_file)
            return True
            
        except Exception as e:
            print(f"备份配置失败: {e}")
            return False
    
    def restore_config(self, backup_file: str | Path) -> bool:
        """从备份恢复配置
        
        Args:
            backup_file: 备份文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                print(f"备份文件不存在: {backup_file}")
                return False
                
            shutil.copy2(backup_path, self.config_file)
            return True
            
        except Exception as e:
            print(f"恢复配置失败: {e}")
            return False
    
    def validate_config_file(self, config_file: str | Path) -> bool:
        """验证配置文件格式
        
        Args:
            config_file: 配置文件路径
            
        Returns:
            bool: 是否有效
        """
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            Config.from_dict(data)
            return True
            
        except Exception as e:
            print(f"配置文件验证失败: {e}")
            return False
    
    def _load_config_dict(self) -> Dict[str, Any]:
        """加载配置字典"""
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_config(self, config: Config):
        """保存配置"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(config), f, indent=2, ensure_ascii=False)
    
    def _validate_config(self, config: Config) -> bool:
        """验证配置"""
        try:
            # 检查 Provider 类型
            valid_types = {"ollama", "openai", "custom"}
            for provider in config.providers.values():
                if provider.type not in valid_types:
                    return False
                    
            # 检查 URL 格式
            for provider in config.providers.values():
                if not provider.base_url.startswith(("http://", "https://")):
                    return False
                    
            return True
            
        except Exception:
            return False
    
    def load(self) -> Config:
        """加载配置"""
        return Config.from_dict(self._load_config_dict())
    
    def save(self, config: Config):
        """保存配置"""
        self._save_config(config)