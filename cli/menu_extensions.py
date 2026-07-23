"""配置管理菜单"""
from __future__ import annotations

import json
import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from .config import load, save, get_current, CONFIG_FILE
from .config_manager import ConfigManager

console = Console()


def config_menu():
    """配置管理菜单"""
    cfg = load()
    config_manager = ConfigManager()
    
    sub = (
        "  [bold yellow]1[/]  查看当前配置\n"
        "  [bold yellow]2[/]  导出配置\n"
        "  [bold yellow]3[/]  导入配置\n"
        "  [bold yellow]4[/]  重置配置\n"
        "  [bold yellow]5[/]  查看配置文件\n"
        "  [bold yellow]6[/]  修复配置\n"
        "  [bold yellow]0[/]  返回"
    )
    
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]配置管理[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if choice == "0":
            break
        elif choice == "1":
            show_current_config(cfg)
        elif choice == "2":
            export_config(config_manager, cfg)
        elif choice == "3":
            import_config(config_manager, cfg)
        elif choice == "4":
            reset_config(config_manager, cfg)
        elif choice == "5":
            show_config_file()
        elif choice == "6":
            fix_config(config_manager, cfg)
        else:
            console.print("[yellow]无效选择，请输入 0-6[/]")


def show_current_config(cfg):
    """显示当前配置"""
    console.print(Panel(
        f"[cyan]配置文件位置:[/] {CONFIG_FILE}\n"
        f"[cyan]Provider 数量:[/] {len(cfg.providers)}\n"
        f"[cyan]当前 Provider:[/] {cfg.current or '未设置'}",
        title="[bold]当前配置[/]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    
    if cfg.providers:
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("名称", style="green")
        table.add_column("类型", style="yellow")
        table.add_column("URL", style="cyan")
        table.add_column("模型", style="white")
        
        for name, prov in cfg.providers.items():
            model = prov.default_model or "未设置"
            table.add_row(name, prov.type, prov.base_url[:50] + "...", model)
        
        console.print(table)


def export_config(config_manager, cfg):
    """导出配置"""
    try:
        export_path = config_manager.export_config()
        console.print(f"[green][OK][/] 配置已导出到: {export_path}")
    except Exception as e:
        console.print(f"[red][X][/] 导出失败: {e}")


def import_config(config_manager, cfg):
    """导入配置"""
    path = console.input("[cyan]输入配置文件路径:[/] ").strip()
    if not path:
        console.print("[yellow]请输入有效的配置文件路径[/]")
        return
        
    try:
        config_manager.import_config(path)
        console.print(f"[green][OK][/] 配置已从 {path} 导入")
    except Exception as e:
        console.print(f"[red][X][/] 导入失败: {e}")


def reset_config(config_manager, cfg):
    """重置配置"""
    confirm = console.input("[red]确认重置所有配置? (y/N):[/] ").strip().lower()
    if confirm == "y":
        try:
            config_manager.reset_config()
            console.print("[green][OK][/] 配置已重置")
        except Exception as e:
            console.print(f"[red][X][/] 重置失败: {e}")


def show_config_file():
    """显示配置文件内容"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        console.print(Panel(
            content,
            title="[bold]配置文件内容[/]",
            border_style="green",
            box=box.ROUNDED
        ))
    except Exception as e:
        console.print(f"[red][X][/] 读取配置文件失败: {e}")


def fix_config(config_manager, cfg):
    """修复配置"""
    try:
        issues = config_manager.validate_config()
        if issues:
            console.print("[yellow]发现配置问题:[/]")
            for issue in issues:
                console.print(f"[red]- {issue}[/]")
                
            fix = console.input("[cyan]自动修复这些问题? (y/N):[/] ").strip().lower()
            if fix == "y":
                config_manager.fix_config()
                console.print("[green][OK][/] 配置已修复")
        else:
            console.print("[green][OK][/] 配置正常，无需修复")
    except Exception as e:
        console.print(f"[red][X][/] 修复失败: {e}")


def theme_menu():
    """主题设置菜单"""
    from .theme import ThemeManager
    
    theme_manager = ThemeManager()
    
    sub = (
        "  [bold yellow]1[/]  查看当前主题\n"
        "  [bold yellow]2[/]  切换主题\n"
        "  [bold yellow]3[/]  列出所有主题\n"
        "  [bold yellow]4[/]  自定义主题\n"
        "  [bold yellow]5[/]  导出主题\n"
        "  [bold yellow]0[/]  返回"
    )
    
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]主题设置[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if choice == "0":
            break
        elif choice == "1":
            show_current_theme(theme_manager)
        elif choice == "2":
            switch_theme(theme_manager)
        elif choice == "3":
            list_themes(theme_manager)
        elif choice == "4":
            customize_theme(theme_manager)
        elif choice == "5":
            export_theme(theme_manager)
        else:
            console.print("[yellow]无效选择，请输入 0-5[/]")


def show_current_theme(theme_manager):
    """显示当前主题"""
    current = theme_manager.get_current_theme()
    console.print(Panel(
        f"[cyan]当前主题:[/] {current.name}\n"
        f"[cyan]描述:[/] {current.description}\n"
        f"[cyan]作者:[/] {current.author}",
        title="[bold]当前主题[/]",
        border_style="cyan",
        box=box.ROUNDED
    ))


def switch_theme(theme_manager):
    """切换主题"""
    themes = theme_manager.list_themes()
    if not themes:
        console.print("[yellow]没有可用主题[/]")
        return
        
    console.print("[cyan]可用主题:[/]")
    for i, theme in enumerate(themes, 1):
        console.print(f"  [bold yellow]{i}[/] {theme.name} - {theme.description}")
    
    try:
        choice = console.input("[cyan]选择主题编号 (1-{}):[/] ".format(len(themes))).strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(themes):
                theme_manager.set_theme(themes[idx])
                console.print(f"[green][OK][/] 已切换到主题: {themes[idx].name}")
            else:
                console.print("[yellow]无效选择[/]")
        else:
            console.print("[yellow]请输入数字[/]")
    except (EOFError, KeyboardInterrupt):
        pass


def list_themes(theme_manager):
    """列出所有主题"""
    themes = theme_manager.list_themes()
    if not themes:
        console.print("[yellow]没有可用主题[/]")
        return
        
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", width=4)
    table.add_column("名称", style="green")
    table.add_column("描述", style="white")
    table.add_column("作者", style="cyan")
    
    for i, theme in enumerate(themes, 1):
        table.add_row(str(i), theme.name, theme.description, theme.author)
    
    console.print(table)


def customize_theme(theme_manager):
    """自定义主题"""
    console.print("[yellow]自定义主题功能开发中...[/]")


def export_theme(theme_manager):
    """导出主题"""
    current = theme_manager.get_current_theme()
    if not current:
        console.print("[yellow]没有当前主题[/]")
        return
        
    try:
        export_path = theme_manager.export_theme(current.name)
        console.print(f"[green][OK][/] 主题已导出到: {export_path}")
    except Exception as e:
        console.print(f"[red][X][/] 导出失败: {e}")


def shortcuts_menu():
    """快捷键设置菜单"""
    from .shortcuts import KeyboardManager
    
    keyboard_manager = KeyboardManager()
    
    sub = (
        "  [bold yellow]1[/]  查看快捷键\n"
        "  [bold yellow]2[/]  编辑快捷键\n"
        "  [bold yellow]3[/]  重置快捷键\n"
        "  [bold yellow]4[/]  导出快捷键\n"
        "  [bold yellow]5[/]  测试快捷键\n"
        "  [bold yellow]0[/]  返回"
    )
    
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]快捷键设置[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if choice == "0":
            break
        elif choice == "1":
            show_shortcuts(keyboard_manager)
        elif choice == "2":
            edit_shortcuts(keyboard_manager)
        elif choice == "3":
            reset_shortcuts(keyboard_manager)
        elif choice == "4":
            export_shortcuts(keyboard_manager)
        elif choice == "5":
            test_shortcuts(keyboard_manager)
        else:
            console.print("[yellow]无效选择，请输入 0-5[/]")


def show_shortcuts(keyboard_manager):
    """显示快捷键"""
    shortcuts = keyboard_manager.get_all_shortcuts()
    if not shortcuts:
        console.print("[yellow]没有设置快捷键[/]")
        return
        
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("快捷键", style="green")
    table.add_column("描述", style="white")
    table.add_column("类别", style="cyan")
    
    for shortcut in shortcuts:
        table.add_row(
            shortcut.key,
            shortcut.description,
            shortcut.category
        )
    
    console.print(table)


def edit_shortcuts(keyboard_manager):
    """编辑快捷键"""
    console.print("[yellow]编辑快捷键功能开发中...[/]")


def reset_shortcuts(keyboard_manager):
    """重置快捷键"""
    confirm = console.input("[red]确认重置所有快捷键? (y/N):[/] ").strip().lower()
    if confirm == "y":
        try:
            keyboard_manager.reset_shortcuts()
            console.print("[green][OK][/] 快捷键已重置")
        except Exception as e:
            console.print(f"[red][X][/] 重置失败: {e}")


def export_shortcuts(keyboard_manager):
    """导出快捷键"""
    try:
        export_path = keyboard_manager.export_shortcuts()
        console.print(f"[green][OK][/] 快捷键已导出到: {export_path}")
    except Exception as e:
        console.print(f"[red][X][/] 导出失败: {e}")


def test_shortcuts(keyboard_manager):
    """测试快捷键"""
    console.print("[yellow]测试快捷键功能开发中...[/]")


def agent_menu():
    """多 Agent 管理菜单"""
    from .multi_agent import AgentOrchestrator
    
    orchestrator = AgentOrchestrator()
    
    sub = (
        "  [bold yellow]1[/]  查看所有 Agent\n"
        "  [bold yellow]2[/]  创建 Agent\n"
        "  [bold yellow]3[/]  启动 Agent\n"
        "  [bold yellow]4[/]  停止 Agent\n"
        "  [bold yellow]5[/]  删除 Agent\n"
        "  [bold yellow]6[/]  Agent 状态\n"
        "  [bold yellow]7[/]  Agent 日志\n"
        "  [bold yellow]0[/]  返回"
    )
    
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]多 Agent 管理[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if choice == "0":
            break
        elif choice == "1":
            list_agents(orchestrator)
        elif choice == "2":
            create_agent(orchestrator)
        elif choice == "3":
            start_agent(orchestrator)
        elif choice == "4":
            stop_agent(orchestrator)
        elif choice == "5":
            delete_agent(orchestrator)
        elif choice == "6":
            agent_status(orchestrator)
        elif choice == "7":
            agent_logs(orchestrator)
        else:
            console.print("[yellow]无效选择，请输入 0-7[/]")


def list_agents(orchestrator):
    """列出所有 Agent"""
    agents = orchestrator.list_agents()
    if not agents:
        console.print("[yellow]没有运行的 Agent[/]")
        return
        
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="green")
    table.add_column("名称", style="white")
    table.add_column("角色", style="cyan")
    table.add_column("状态", style="yellow")
    table.add_column("模型", style="magenta")
    
    for agent in agents:
        status = "运行中" if agent.is_running else "已停止"
        table.add_row(
            agent.id[:8],
            agent.name,
            agent.role.value,
            status,
            agent.model
        )
    
    console.print(table)


def create_agent(orchestrator):
    """创建 Agent"""
    name = console.input("[cyan]Agent 名称:[/] ").strip()
    if not name:
        console.print("[yellow]请输入 Agent 名称[/]")
        return
        
    role_choice = console.input("[cyan]Agent 角色 (coder/researcher/analyst):[/] ").strip()
    role = role_choice.lower()
    
    model = console.input("[cyan]模型名称:[/] ").strip()
    if not model:
        console.print("[yellow]请输入模型名称[/]")
        return
        
    try:
        agent = orchestrator.create_agent(name, role, model)
        console.print(f"[green][OK][/] Agent {name} 创建成功")
    except Exception as e:
        console.print(f"[red][X][/] 创建失败: {e}")


def start_agent(orchestrator):
    """启动 Agent"""
    agent_id = console.input("[cyan]Agent ID (前8位):[/] ").strip()
    if not agent_id:
        console.print("[yellow]请输入 Agent ID[/]")
        return
        
    try:
        orchestrator.start_agent(agent_id)
        console.print(f"[green][OK][/] Agent 已启动")
    except Exception as e:
        console.print(f"[red][X][/] 启动失败: {e}")


def stop_agent(orchestrator):
    """停止 Agent"""
    agent_id = console.input("[cyan]Agent ID (前8位):[/] ").strip()
    if not agent_id:
        console.print("[yellow]请输入 Agent ID[/]")
        return
        
    try:
        orchestrator.stop_agent(agent_id)
        console.print(f"[green][OK][/] Agent 已停止")
    except Exception as e:
        console.print(f"[red][X][/] 停止失败: {e}")


def delete_agent(orchestrator):
    """删除 Agent"""
    agent_id = console.input("[cyan]Agent ID (前8位):[/] ").strip()
    if not agent_id:
        console.print("[yellow]请输入 Agent ID[/]")
        return
        
    confirm = console.input("[red]确认删除此 Agent? (y/N):[/] ").strip().lower()
    if confirm == "y":
        try:
            orchestrator.delete_agent(agent_id)
            console.print(f"[green][OK][/] Agent 已删除")
        except Exception as e:
            console.print(f"[red][X][/] 删除失败: {e}")


def agent_status(orchestrator):
    """查看 Agent 状态"""
    agent_id = console.input("[cyan]Agent ID (前8位):[/] ").strip()
    if not agent_id:
        console.print("[yellow]请输入 Agent ID[/]")
        return
        
    try:
        status = orchestrator.get_agent_status(agent_id)
        console.print(Panel(
            status,
            title=f"[bold]Agent {agent_id} 状态[/]",
            border_style="cyan",
            box=box.ROUNDED
        ))
    except Exception as e:
        console.print(f"[red][X][/] 获取状态失败: {e}")


def agent_logs(orchestrator):
    """查看 Agent 日志"""
    agent_id = console.input("[cyan]Agent ID (前8位):[/] ").strip()
    if not agent_id:
        console.print("[yellow]请输入 Agent ID[/]")
        return
        
    try:
        logs = orchestrator.get_agent_logs(agent_id)
        console.print(Panel(
            logs,
            title=f"[bold]Agent {agent_id} 日志[/]",
            border_style="green",
            box=box.ROUNDED
        ))
    except Exception as e:
        console.print(f"[red][X][/] 获取日志失败: {e}")