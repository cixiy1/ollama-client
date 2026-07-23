"""自动补全系统 — 支持命令行自动补全"""
from __future__ import annotations

import re
from typing import List, Dict, Optional, Callable, Any, Union
from dataclasses import dataclass
from enum import Enum


class CompletionType(Enum):
    """补全类型"""
    COMMAND = "command"
    TOOL = "tool"
    OPTION = "option"
    FILE = "file"
    DIRECTORY = "directory"
    PROVIDER = "provider"
    MODEL = "model"
    CONTEXT = "context"


@dataclass
class CompletionItem:
    """补全项"""
    text: str
    display_text: str
    description: str = ""
    type: CompletionType = CompletionType.COMMAND
    category: str = "general"
    score: int = 0  # 匹配分数，用于排序
    
    def to_display(self) -> str:
        """转换为显示字符串"""
        if self.description:
            return f"{self.display_text:<20} {self.description}"
        return self.display_text


@dataclass
class CompletionContext:
    """补全上下文"""
    current_line: str
    cursor_position: int
    previous_words: List[str]
    current_word: str
    full_command: str


class AutoCompleter:
    """自动补全器"""
    
    def __init__(self):
        self.completers: Dict[CompletionType, Callable] = {}
        self.commands: Dict[str, CompletionItem] = {}
        self.tools: Dict[str, CompletionItem] = {}
        self.options: Dict[str, Dict[str, CompletionItem]] = {}
        
        self._register_builtin_completers()
        self._register_builtin_commands()
    
    def _register_builtin_completers(self):
        """注册内置补全器"""
        self.completers[CompletionType.COMMAND] = self._complete_command
        self.completers[CompletionType.TOOL] = self._complete_tool
        self.completers[CompletionType.OPTION] = self._complete_option
        self.completers[CompletionType.FILE] = self._complete_file
        self.completers[CompletionType.DIRECTORY] = self._complete_directory
        self.completers[CompletionType.PROVIDER] = self._complete_provider
        self.completers[CompletionType.MODEL] = self._complete_model
        self.completers[CompletionType.CONTEXT] = self._complete_context
    
    def _register_builtin_commands(self):
        """注册内置命令"""
        self.commands.update({
            "help": CompletionItem(
                text="help",
                display_text="help",
                description="显示帮助信息",
                type=CompletionType.COMMAND,
                category="general"
            ),
            "status": CompletionItem(
                text="status",
                display_text="status",
                description="显示系统状态",
                type=CompletionType.COMMAND,
                category="general"
            ),
            "config": CompletionItem(
                text="config",
                display_text="config",
                description="配置管理",
                type=CompletionType.COMMAND,
                category="general"
            ),
            "theme": CompletionItem(
                text="theme",
                display_text="theme",
                description="主题管理",
                type=CompletionType.COMMAND,
                category="general"
            ),
            "tools": CompletionItem(
                text="tools",
                display_text="tools",
                description="显示工具列表",
                type=CompletionType.COMMAND,
                category="tools"
            ),
            "sessions": CompletionItem(
                text="sessions",
                display_text="sessions",
                description="会话管理",
                type=CompletionType.COMMAND,
                category="chat"
            ),
            "usage": CompletionItem(
                text="usage",
                display_text="usage",
                description="使用统计",
                type=CompletionType.COMMAND,
                category="general"
            ),
            "plan": CompletionItem(
                text="plan",
                display_text="plan",
                description="计划模式",
                type=CompletionType.COMMAND,
                category="agent"
            ),
            "retry": CompletionItem(
                text="retry",
                display_text="retry",
                description="重试对话",
                type=CompletionType.COMMAND,
                category="chat"
            ),
            "undo": CompletionItem(
                text="undo",
                display_text="undo",
                description="撤销对话",
                type=CompletionType.COMMAND,
                category="chat"
            ),
            "compact": CompletionItem(
                text="compact",
                display_text="compact",
                description="紧凑历史",
                type=CompletionType.COMMAND,
                category="chat"
            ),
        })
    
    def add_command(self, command: CompletionItem):
        """添加命令"""
        self.commands[command.text] = command
    
    def add_tool(self, tool: CompletionItem):
        """添加工具"""
        self.tools[tool.text] = tool
    
    def add_option(self, command: str, option: CompletionItem):
        """添加选项"""
        if command not in self.options:
            self.options[command] = {}
        self.options[command][option.text] = option
    
    def get_completions(self, context: CompletionContext) -> List[CompletionItem]:
        """获取补全建议"""
        completions = []
        
        # 根据当前单词确定补全类型
        completion_type = self._determine_completion_type(context)
        
        if completion_type in self.completers:
            completer = self.completers[completion_type]
            completions = completer(context)
        
        # 按分数排序
        completions.sort(key=lambda x: x.score, reverse=True)
        
        return completions
    
    def _determine_completion_type(self, context: CompletionContext) -> CompletionType:
        """确定补全类型"""
        words = context.previous_words
        
        if not words:
            return CompletionType.COMMAND
        
        # 第一个单词是命令
        if len(words) == 1:
            command = words[0]
            
            # 检查是否有该命令的选项
            if command in self.options:
                return CompletionType.OPTION
            
            # 根据命令类型返回不同的补全
            if command in ["config", "theme"]:
                return CompletionType.OPTION
            elif command in ["read", "write", "edit"]:
                return CompletionType.FILE
            elif command == "cd":
                return CompletionType.DIRECTORY
        
        # 第二个单词及以后
        if len(words) >= 2:
            command = words[0]
            
            if command == "config" and len(words) == 2:
                return CompletionType.OPTION
            elif command in ["read", "write", "edit"] and len(words) == 2:
                return CompletionType.FILE
            elif command == "cd" and len(words) == 2:
                return CompletionType.DIRECTORY
        
        return CompletionType.COMMAND
    
    def _complete_command(self, context: CompletionContext) -> List[CompletionItem]:
        """补全命令"""
        current_word = context.current_word.lower()
        completions = []
        
        for command in self.commands.values():
            if current_word in command.text.lower():
                score = self._calculate_score(command.text, current_word)
                completion = CompletionItem(
                    text=command.text,
                    display_text=command.display_text,
                    description=command.description,
                    type=CompletionType.COMMAND,
                    category=command.category,
                    score=score
                )
                completions.append(completion)
        
        return completions
    
    def _complete_tool(self, context: CompletionContext) -> List[CompletionItem]:
        """补全工具"""
        current_word = context.current_word.lower()
        completions = []
        
        for tool in self.tools.values():
            if current_word in tool.text.lower():
                score = self._calculate_score(tool.text, current_word)
                completion = CompletionItem(
                    text=tool.text,
                    display_text=tool.display_text,
                    description=tool.description,
                    type=CompletionType.TOOL,
                    category=tool.category,
                    score=score
                )
                completions.append(completion)
        
        return completions
    
    def _complete_option(self, context: CompletionContext) -> List[CompletionItem]:
        """补全选项"""
        if len(context.previous_words) < 2:
            return []
        
        command = context.previous_words[0]
        current_word = context.current_word.lower()
        completions = []
        
        if command in self.options:
            for option in self.options[command].values():
                if current_word in option.text.lower():
                    score = self._calculate_score(option.text, current_word)
                    completion = CompletionItem(
                        text=option.text,
                        display_text=option.display_text,
                        description=option.description,
                        type=CompletionType.OPTION,
                        category=option.category,
                        score=score
                    )
                    completions.append(completion)
        
        return completions
    
    def _complete_file(self, context: CompletionContext) -> List[CompletionItem]:
        """补全文件"""
        import os
        
        current_word = context.current_word
        if not current_word:
            current_word = "."
        
        # 获取目录路径
        directory = os.path.dirname(current_word) or "."
        filename = os.path.basename(current_word)
        
        if not os.path.exists(directory):
            return []
        
        completions = []
        try:
            for item in os.listdir(directory):
                full_path = os.path.join(directory, item)
                
                if item.lower().startswith(filename.lower()):
                    if os.path.isfile(full_path):
                        completion = CompletionItem(
                            text=full_path,
                            display_text=item,
                            description="文件",
                            type=CompletionType.FILE,
                            category="file",
                            score=self._calculate_score(item, filename)
                        )
                        completions.append(completion)
                    elif os.path.isdir(full_path):
                        completion = CompletionItem(
                            text=full_path + "/",
                            display_text=item + "/",
                            description="目录",
                            type=CompletionType.DIRECTORY,
                            category="directory",
                            score=self._calculate_score(item, filename)
                        )
                        completions.append(completion)
        except PermissionError:
            pass
        
        return completions
    
    def _complete_directory(self, context: CompletionContext) -> List[CompletionItem]:
        """补全目录"""
        return self._complete_file(context)
    
    def _complete_provider(self, context: CompletionContext) -> List[CompletionItem]:
        """补全 Provider"""
        current_word = context.current_word.lower()
        completions = []
        
        # 这里应该从配置中获取 Provider 列表
        # 现在使用固定的 Provider 列表
        providers = ["ollama", "openai", "custom"]
        
        for provider in providers:
            if current_word in provider.lower():
                score = self._calculate_score(provider, current_word)
                completion = CompletionItem(
                    text=provider,
                    display_text=provider,
                    description=f"{provider} provider",
                    type=CompletionType.PROVIDER,
                    category="provider",
                    score=score
                )
                completions.append(completion)
        
        return completions
    
    def _complete_model(self, context: CompletionContext) -> List[CompletionItem]:
        """补全模型"""
        current_word = context.current_word.lower()
        completions = []
        
        # 这里应该从 API 获取模型列表
        # 现在使用固定的模型列表
        models = ["qwen2.5:7b", "gpt-4", "gpt-3.5-turbo", "custom-model"]
        
        for model in models:
            if current_word in model.lower():
                score = self._calculate_score(model, current_word)
                completion = CompletionItem(
                    text=model,
                    display_text=model,
                    description=f"模型: {model}",
                    type=CompletionType.MODEL,
                    category="model",
                    score=score
                )
                completions.append(completion)
        
        return completions
    
    def _complete_context(self, context: CompletionContext) -> List[CompletionItem]:
        """补全上下文文件"""
        current_word = context.current_word.lower()
        completions = []
        
        # 这里应该从上下文文件系统中获取文件列表
        # 现在使用固定的文件列表
        context_files = ["README.md", "CLAUDE.md", "CONTEXT.md", "NOTES.md"]
        
        for file in context_files:
            if current_word in file.lower():
                score = self._calculate_score(file, current_word)
                completion = CompletionItem(
                    text=file,
                    display_text=file,
                    description="上下文文件",
                    type=CompletionType.CONTEXT,
                    category="context",
                    score=score
                )
                completions.append(completion)
        
        return completions
    
    def _calculate_score(self, text: str, query: str) -> int:
        """计算匹配分数"""
        if text == query:
            return 100
        
        if text.startswith(query):
            return 90
        
        if query in text:
            return 70
        
        # 计算字符匹配度
        score = 0
        for i, char in enumerate(query):
            if i < len(text) and text[i] == char:
                score += 10
        
        return score
    
    def format_completions(self, completions: List[CompletionItem], max_items: int = 10) -> str:
        """格式化补全显示"""
        if not completions:
            return ""
        
        # 限制显示数量
        completions = completions[:max_items]
        
        # 找出最长的显示文本
        max_length = max(len(item.display_text) for item in completions)
        
        lines = []
        for item in completions:
            line = f"{item.display_text:<{max_length}}  {item.description}"
            lines.append(line)
        
        return "\n".join(lines)


class CompletionEngine:
    """补全引擎"""
    
    def __init__(self):
        self.completer = AutoCompleter()
        self.enabled = True
    
    def complete(self, line: str, cursor_pos: int) -> tuple[str, List[CompletionItem]]:
        """执行补全"""
        if not self.enabled:
            return line, []
        
        # 解析上下文
        context = self._parse_context(line, cursor_pos)
        
        # 获取补全建议
        completions = self.completer.get_completions(context)
        
        # 返回补全文本和列表
        common_prefix = self._find_common_prefix(completions)
        
        return common_prefix, completions
    
    def _parse_context(self, line: str, cursor_pos: int) -> CompletionContext:
        """解析补全上下文"""
        # 获取当前光标位置之前的文本
        before_cursor = line[:cursor_pos]
        
        # 分割单词
        words = before_cursor.split()
        current_word = words[-1] if words else ""
        
        # 获取完整命令
        full_command = " ".join(words[:-1]) if len(words) > 1 else ""
        
        return CompletionContext(
            current_line=line,
            cursor_position=cursor_pos,
            previous_words=words[:-1] if words else [],
            current_word=current_word,
            full_command=full_command
        )
    
    def _find_common_prefix(self, completions: List[CompletionItem]) -> str:
        """找到公共前缀"""
        if not completions:
            return ""
        
        # 获取所有补全文本
        texts = [item.text for item in completions]
        
        if len(texts) == 1:
            return texts[0]
        
        # 找到公共前缀
        common_prefix = texts[0]
        for text in texts[1:]:
            i = 0
            while i < min(len(common_prefix), len(text)) and common_prefix[i] == text[i]:
                i += 1
            common_prefix = common_prefix[:i]
        
        return common_prefix