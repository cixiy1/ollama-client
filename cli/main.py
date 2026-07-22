"""CLI 命令行界面 — 菜单模式 + 会话历史 + 上下文感知 + 工具系统"""
from __future__ import annotations

import argparse
import json
import os
import sys
from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.table import Table
from rich.rule import Rule
from rich.align import Align
from rich.spinner import Spinner
from rich import box

from .config import (
    load, save, add, remove, rename, get_current, CONFIG_FILE)
from .api import YukiAPI, Provider
from .session import SessionStore, Session, Message
from .context import (
    discover_context_files, summarize_contexts,
    inject_into_messages, load_context_for_directory)
from .tools import ToolRegistry
from .usage import UsageStore

console = Console()


# ---- 全局 store 实例 ----

_session_store = SessionStore()
_usage_store = UsageStore()
_tool_registry = ToolRegistry()


# ---- 思考标签清理 ----

def _strip_think_tags(text: str) -> str:
    """去掉文本中所有<think>...</think> 标签"""
    while True:
        i = text.find("<think>")
        j = text.find("</think>", i if i != -1 else 0)
        if j == -1:
            if i == -1:
                break
            text = text[:i] + text[i + 6:]
        else:
            text = text[:i] + text[j + 7:] if i != -1 else text
    return text


# ---- 流式渲染 ----

def _build_window(thinking_text: str, answer_text: str, thinking_done: bool) -> Group:
    cards = []
    if thinking_text.strip():
        status = "[dim italic]思考中..." if not thinking_done else "[dim]完成[/]"
        body = Text(thinking_text, style="dim", overflow="fold", no_wrap=False)
        cards.append(Panel(body,
            title="[bold yellow][think] 推理过程[/]",
            title_align="left",
            subtitle=status,
            subtitle_align="right",
            border_style="yellow",
            box=box.ROUNDED,
            padding=(1, 2)))
    if answer_text.strip():
        answer_text = _strip_think_tags(answer_text)
        body = Text(answer_text, style="white", overflow="fold", no_wrap=False)
        cards.append(Panel(body,
            title="[bold green] 回答[/]",
            title_align="left",
            border_style="green",
            box=box.ROUNDED,
            padding=(1, 2)))
    if not cards:
        cards.append(Panel(
            Align.center(Spinner("dots", text="模型正在生成..."), vertical="middle"),
            border_style="cyan", box=box.ROUNDED, padding=(1, 2)))
    return Group(*cards)


def _stream_and_render(stream, title: str = "") -> str:
    thinking_buf = ""
    answer_buf = ""
    in_thinking = False
    thinking_done = False
    finished = False

    header = (Panel(
        Align.center(f"[bold cyan]{title}[/]" if title else "[bold cyan]Yuki Code[/]",
                     vertical="middle"),
        border_style="bright_blue", box=box.DOUBLE, padding=(0, 1), expand=True)
        if title else None)

    def render():
        grp = _build_window(thinking_buf, answer_buf, thinking_done)
        return Group(header, grp) if header else grp

    with Live(render(), console=console, refresh_per_second=12, transient=False) as live:
        for kind, text in stream:
            if finished:
                break
            if kind == "thinking":
                thinking_buf += text
            else:
                while text:
                    if not in_thinking:
                        idx = text.find("<think>")
                        if idx == -1:
                            answer_buf += text
                            text = ""
                        else:
                            answer_buf += text[:idx]
                            text = text[idx + 6:]
                            in_thinking = True
                    else:
                        idx = text.find("</think>")
                        if idx == -1:
                            thinking_buf += text
                            text = ""
                        else:
                            thinking_buf += text[:idx]
                            text = text[idx + 7:]
                            in_thinking = False
                            thinking_done = True
            live.update(render())
        thinking_done = True
        in_thinking = False
        finished = True
        live.update(render())
    console.print(render())
    return answer_buf


# ---- Provider 感知 API 创建 ----

def _make_api(args) -> YukiAPI:
    cfg = load()
    if args.provider:
        prov = cfg.providers.get(args.provider)
        if not prov:
            console.print(f"[red]未找到 Provider: {args.provider}[/]")
            sys.exit(1)
    elif args.url:
        prov = Provider(type="custom", name=args.url, base_url=args.url,
                        timeout=args.timeout)
    else:
        prov = get_current()
        if not prov:
            console.print("[red]未配置任何 Provider，请先运行 yuki config add 或 --url[/]")
            sys.exit(1)
    return YukiAPI(prov, session_store=_session_store, usage_store=_usage_store)


# ---- 命令实现 ----

def cmd_status(api: YukiAPI, provider_name: str):
    try:
        online = api.ping()
    except Exception:
        online = False
    if online:
        console.print(f"[green][*][/] 服务在线   [dim]{api.provider.base_url}[/]"
                      f"   [dim]|[/]   [{api.provider.type}] {api.provider.name}")
    else:
        console.print(f"[red][X][/] 服务离线   [dim]{api.provider.base_url}[/]"
                      f"   [dim]|[/]   [{api.provider.type}] {api.provider.name}")
    try:
        models = api.list_models()
        console.print(f"[green][*][/] 可用模型   [bold cyan]{len(models)}[/] 个")
    except Exception:
        pass


def cmd_list(api: YukiAPI):
    try:
        models = api.list_models()
    except Exception as e:
        console.print(f"[red][X][/] 获取模型列表失败: {e}")
        return
    if not models:
        console.print("[yellow]未检测到任何模型[/]")
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="bold yellow", width=4)
    table.add_column("模型名称", style="green")
    if api.provider.type == "ollama":
        table.add_column("大小", justify="right")
        table.add_column("更新时间", style="dim")
        for i, m in enumerate(models, 1):
            table.add_row(str(i), m.name, api.format_size(m.size), m.modified[:16])
    else:
        for i, m in enumerate(models, 1):
            table.add_row(str(i), m.name)
    console.print(table)


def cmd_info(api: YukiAPI, model: str):
    if api.provider.type != "ollama":
        console.print("[yellow]当前 Provider 类型不支持查看模型详情[/]")
        return
    try:
        info = api.show_model_info(model)
    except Exception as e:
        console.print(f"[red][X][/] 获取失败: {e}")
        return
    if "error" in info:
        console.print(f"[red]{info['error']}[/]")
        return
    table = Table(box=None, show_header=False)
    for k, v in info.items():
        table.add_row(f"[cyan]{k}[/]", str(v))
    console.print(Panel(table, title=f"[green]{model}[/]", border_style="green"))


def cmd_pull(api: YukiAPI, name: str):
    if api.provider.type != "ollama":
        console.print("[yellow]当前 Provider 类型不支持拉取模型[/]")
        return
    console.print(f"[cyan]开始拉取 {name}...[/]  (Ctrl+C 中断)\n")
    try:
        for status in api.pull_model(name):
            console.print(status)
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/]")


def cmd_delete(api: YukiAPI, name: str):
    if api.provider.type != "ollama":
        console.print("[yellow]当前 Provider 类型不支持删除模型[/]")
        return
    if api.delete_model(name):
        console.print(f"[green][OK][/] 已删除 {name}")
    else:
        console.print(f"[red][X][/] 删除失败")


def cmd_tools(registry: ToolRegistry):
    """列出所有可用工具"""
    infos = registry.tool_infos()
    table = Table(show_header=True, header_style="bold cyan",
                  title=f"[bold]可用工具 ({len(infos)} 个)[/]")
    table.add_column("名称", style="green", width=16)
    table.add_column("描述", style="white")
    for info in infos:
        table.add_row(info.name, info.description)
    console.print(table)


def cmd_tools_exec(name: str, params_str: str, registry: ToolRegistry):
    """执行单个工具"""
    try:
        params = {} if not params_str else json.loads(params_str)
    except json.JSONDecodeError:
        console.print(f"[red]工具参数必须是有效的 JSON: {params_str}[/]")
        return
    result = registry.execute(name, params)
    console.print(Panel(
        f"[green]工具:[/] {name}\n"
        f"[green]结果:[/]\n{result.content}",
        title=f"[bold]{'错误' if result.is_error else '成功'}[/]",
        border_style="red" if result.is_error else "green",
        box=box.ROUNDED))


def cmd_sessions():
    """列出最近的会话"""
    sessions = _session_store.list_sessions(limit=20)
    if not sessions:
        console.print("[dim]暂无会话记录[/]")
        return
    table = Table(show_header=True, header_style="bold cyan",
                  title=f"[bold]最近会话 ({len(sessions)} 条)[/]")
    table.add_column("#", width=4)
    table.add_column("标题", style="green")
    table.add_column("Provider", style="cyan")
    table.add_column("模型", style="yellow")
    table.add_column("更新", style="dim")
    for i, s in enumerate(sessions, 1):
        from datetime import datetime
        t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
        table.add_row(str(i), s.title[:40], s.provider or "-",
                      s.model[:20], t)
    console.print(table)


def cmd_usage_summary():
    """显示 Token 用量汇总"""
    summary = _usage_store.summary(days=30)
    table = Table(box=None, show_header=False,
                  title="[bold]Token 用量统计（近 30 天）[/]")
    table.add_row("[cyan]输入 Token:[/]", f"[yellow]{summary['input_tokens']:,}[/]")
    table.add_row("[cyan]输出 Token:[/]", f"[yellow]{summary['output_tokens']:,}[/]")
    table.add_row("[cyan]总 Token:[/]",   f"[bold yellow]{summary['total_tokens']:,}[/]")
    table.add_row("[cyan]估算费用:[/]",   f"[yellow]${summary['cost_usd']:.4f}[/]")
    table.add_row("[cyan]请求次数:[/]",  f"[cyan]{summary['requests']}[/]")
    console.print(Panel(table, border_style="cyan", box=box.ROUNDED))


def cmd_chat(api: YukiAPI, model: str, system: str | None, temp: float,
             stdin: bool, session_id: str | None = None,
             cwd: str | None = None):
    """
    对话命令，支持：
    - 会话历史自动持久化
    - 上下文文件自动加载
    - 特殊指令: /quit /clear /models /tools /tool /sessions /usage
    """
    # 加载上下文文件
    work_dir = cwd or os.getcwd()
    contexts = discover_context_files(work_dir)

    # 获取或创建会话
    if session_id:
        session = _session_store.get_session(session_id)
        if session:
            messages = [{"role": m.role, "content": m.content} for m in session.messages]
        else:
            console.print(f"[yellow]会话 {session_id} 不存在，创建新会话[/]")
            session = _session_store.create_session(
                provider=api.provider.label or api.provider.type,
                model=model)
            messages = []
    else:
        session = _session_store.create_session(
            provider=api.provider.label or api.provider.type,
            model=model)
        messages = []

    # 构建 system 消息（含上下文）
    ctx_text = load_context_for_directory(work_dir)
    system_parts = []
    if ctx_text:
        system_parts.append(ctx_text)
    if system:
        system_parts.append(system)
    if system_parts:
        system_content = "\n\n".join(system_parts)
        messages.insert(0, {"role": "system", "content": system_content})
        console.print(f"[dim]System + 上下文:[/] {len(ctx_text)} 字")

    console.print()
    console.print(Rule(f"[bold green][chat] 对话中[/]  [cyan]{model}[/]"
                        f"[dim]  会话 {session.id[:8]}[/]"))
    if contexts:
        console.print(f"[dim]已加载上下文文件:[/]\n{summarize_contexts(contexts)}")
    console.print("[dim]指令: /quit /clear /models /tools /tool /sessions /usage\n")

    # 注入上下文到 messages
    if contexts and not any(m.get("role") == "system" for m in messages):
        messages = inject_into_messages(contexts, messages)

    if stdin:
        content = sys.stdin.read().strip()
        messages.append({"role": "user", "content": content})
        console.print(f"[cyan]You (pipe):[/] {content[:100]}...")
        _session_store.add_message(session.id, Message(
            role="user", content=content, model=model))
        response = _stream_and_render(
            api.chat(model, messages, temperature=temp, stream=True),
            title=model)
        _session_store.add_message(session.id, Message(
            role="assistant", content=response, model=model))
        if session.title == "新对话":
            _session_store.auto_title(session.id)
        return

    while True:
        try:
            user_input = console.input("[cyan]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]退出对话[/]")
            break
        if not user_input:
            continue

        # ---- 内置指令 ----
        if user_input in ("/quit", "/exit", "quit", "exit"):
            console.print("[dim]退出对话[/]")
            break
        if user_input == "/clear":
            messages = [m for m in messages if m.get("role") == "system"]
            console.print("[dim]对话历史已清除[/]")
            continue
        if user_input == "/models":
            cmd_list(api)
            continue
        if user_input == "/tools":
            cmd_tools(_tool_registry)
            continue
        if user_input.startswith("/tool "):
            parts = user_input[6:].split(maxsplit=1)
            name = parts[0]
            params = parts[1] if len(parts) > 1 else "{}"
            cmd_tools_exec(name, params, _tool_registry)
            continue
        if user_input == "/sessions":
            cmd_sessions()
            continue
        if user_input == "/usage":
            cmd_usage_summary()
            continue
        if user_input == "/contexts":
            if contexts:
                console.print(f"[dim]当前上下文文件:[/]")
                console.print(summarize_contexts(contexts))
            else:
                console.print("[dim]未发现上下文规范文件[/]")
            continue

        messages.append({"role": "user", "content": user_input})

        # 追加到会话历史
        _session_store.add_message(session.id, Message(
            role="user", content=user_input, model=model))

        console.print()
        response = ""
        try:
            response = _stream_and_render(
                api.chat(model, messages, temperature=temp, stream=True),
                title=model)
        except KeyboardInterrupt:
            print()
            console.print("[yellow]已中断生成[/]")
            messages.append({"role": "assistant", "content": response})
            break
        messages.append({"role": "assistant", "content": response})

        # 保存助手回复到会话
        _session_store.add_message(session.id, Message(
            role="assistant", content=response, model=model))

        # 自动生成标题（第一条用户消息作为标题）
        if session.title == "新对话":
            _session_store.auto_title(session.id)

        console.print()


def cmd_generate(api: YukiAPI, model: str, prompt: str, temp: float,
                 cwd: str | None = None):
    console.print()
    console.print(Rule(f"[bold cyan][gen] 生成[/]  [green]{model}[/]"))

    # 自动加载上下文
    work_dir = cwd or os.getcwd()
    contexts = discover_context_files(work_dir)
    full_prompt = prompt
    if contexts:
        ctx_text = load_context_for_directory(work_dir)
        full_prompt = ctx_text + "\n\n用户请求:\n" + prompt
        console.print(f"[dim]已注入 {len(contexts)} 个上下文文件 ({len(ctx_text)} 字)[/]")
    console.print(f"[dim]提示词:[/] {prompt}\n")

    try:
        _stream_and_render(
            api.generate(model, full_prompt, temperature=temp, stream=True),
            title=model)
    except Exception as e:
        console.print(f"\n[red]生成失败: {e}[/]")


def cmd_running(api: YukiAPI):
    if api.provider.type != "ollama":
        console.print("[yellow]当前 Provider 类型不支持查看已加载模型[/]")
        return
    try:
        models = api.running_models()
    except Exception as e:
        console.print(f"[red][X][/] 获取失败: {e}")
        return
    if not models:
        console.print("[yellow]当前没有加载任何模型[/]")
        return
    table = Table(title="当前加载的模型", show_header=True, header_style="bold cyan")
    table.add_column("模型名称", style="green")
    table.add_column("大小", justify="right")
    table.add_column("已加载时间", style="dim")
    for m in models:
        size = api.format_size(m.get("size", 0))
        dur = m.get("duration", 0)
        table.add_row(m.get("name", "-"), size, f"{dur:.1f}s" if dur else "-")
    console.print(table)


# ---- Provider 管理命令 ----

def cmd_config_list():
    cfg = load()
    table = Table(show_header=True, header_style="bold cyan",
                  title=f"[bold]Provider 列表[/]  (当前: [yellow]{cfg.current or '(无)'}[/])")
    table.add_column("#", width=4)
    table.add_column("名称", style="green")
    table.add_column("类型", style="cyan")
    table.add_column("地址", style="dim")
    table.add_column("默认模型", style="dim")
    for i, (k, v) in enumerate(cfg.providers.items(), 1):
        marker = " *" if k == cfg.current else ""
        table.add_row(str(i), f"{k}{marker}", v.type, v.base_url, v.default_model or "-")
    console.print(table)
    console.print(f"\n[dim]配置文件: {CONFIG_FILE}[/]")


def cmd_config_add(name: str, ptype: str, url: str, api_key: str,
                    default_model: str, timeout: int):
    if not name or not ptype or not url:
        console.print("[red]缺少必要参数: --name --type --url[/]")
        sys.exit(1)
    if ptype not in ("ollama", "openai", "custom"):
        console.print(f"[red]type 必须是 ollama | openai | custom[/]")
        sys.exit(1)
    prov = Provider(
        type=ptype,
        name=name or url,
        base_url=url,
        api_key=api_key or "",
        default_model=default_model or "",
        timeout=timeout or 120,
        label=ptype,
    )
    cfg = load()
    if name in cfg.providers:
        console.print(f"[yellow]Provider '{name}' 已存在，将覆盖[/]")
    add(name, prov)
    console.print(f"[green][OK][/] 已添加 Provider: {name}  [{ptype}]  {url}")


def cmd_config_remove(name: str):
    if not name:
        console.print("[red]缺少参数: --name[/]")
        sys.exit(1)
    if remove(name):
        console.print(f"[green][OK][/] 已删除 Provider: {name}")
    else:
        console.print(f"[red]未找到 Provider: {name}[/]")


def cmd_config_rename(old: str, new: str):
    if not old or not new:
        console.print("[red]缺少参数: --old --new[/]")
        sys.exit(1)
    if rename(old, new):
        console.print(f"[green][OK][/] 已将 '{old}' 重命名为 '{new}'")
    else:
        console.print(f"[red]重命名失败[/]")


# ---- 交互式主界面 ----

def _pick_model(api: YukiAPI, prompt_text: str = "选择模型序号") -> str | None:
    try:
        models = api.list_models()
    except Exception as e:
        console.print(f"[red][X][/] 获取模型列表失败: {e}")
        return None
    if not models:
        console.print("[yellow]未检测到任何可用模型[/]")
        return None
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", style="bold yellow", width=4)
    table.add_column("模型名称", style="green")
    if api.provider.type == "ollama":
        table.add_column("大小", justify="right")
        for i, m in enumerate(models, 1):
            table.add_row(str(i), m.name, api.format_size(m.size))
    else:
        for i, m in enumerate(models, 1):
            table.add_row(str(i), m.name)
    console.print(table)
    while True:
        choice = console.input(
            f"[cyan]{prompt_text} (1-{len(models)}, 回车取消):[/] ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1].name
        console.print("[yellow]输入无效[/]")


def _pick_provider(prompt_text: str = "选择 Provider 序号") -> str | None:
    cfg = load()
    if not cfg.providers:
        return None
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", style="bold yellow", width=4)
    table.add_column("名称", style="green")
    table.add_column("类型", style="cyan")
    table.add_column("地址", style="dim")
    items = list(cfg.providers.items())
    for i, (k, v) in enumerate(items, 1):
        marker = " *" if k == cfg.current else ""
        table.add_row(str(i), f"{k}{marker}", v.type, v.base_url)
    console.print(table)
    while True:
        choice = console.input(
            f"[cyan]{prompt_text} (1-{len(items)}, 回车取消):[/] ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1][0]
        console.print("[yellow]输入无效[/]")


def _pick_session() -> str | None:
    sessions = _session_store.list_sessions(limit=15)
    if not sessions:
        console.print("[dim]暂无会话记录[/]")
        return None
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", style="bold yellow", width=4)
    table.add_column("ID", style="dim")
    table.add_column("标题", style="green")
    table.add_column("模型", style="cyan")
    table.add_column("更新", style="dim")
    for i, s in enumerate(sessions, 1):
        from datetime import datetime
        t = datetime.fromtimestamp(s.updated_at).strftime("%m-%d %H:%M")
        table.add_row(str(i), s.id[:8], s.title[:35], s.model[:20], t)
    console.print(table)
    while True:
        choice = console.input(
            f"[cyan]选择要恢复的会话 (1-{len(sessions)}, 回车新建):[/] ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(sessions):
            return sessions[int(choice) - 1].id
        console.print("[yellow]输入无效[/]")


def interactive(args):
    cfg = load()
    prov = get_current()

    console.print()
    console.print(Panel(
        "[bold cyan]Yuki Code[/]\n[dim]多 Provider AI 代码助手[/]\n"
        "[dim]会话历史 | 上下文感知 | 工具系统[/]",
        box=box.DOUBLE, border_style="cyan", padding=(0, 4), expand=False))

    if not cfg.providers:
        console.print(Panel(
            "[yellow]未配置任何 Provider[/]\n\n"
            "请先添加 Provider：\n"
            "  [cyan]yuki config add --name ollama --type ollama --url http://localhost:11434[/]",
            title="[bold]欢迎[/]", border_style="yellow", box=box.ROUNDED))
        return

    api = YukiAPI(prov, session_store=_session_store, usage_store=_usage_store)

    if not api.ping():
        console.print(Panel(
            f"[red][X] 无法连接 {api.provider.base_url}[/]\n"
            f"[dim]类型: {api.provider.type} | {api.provider.name}[/]\n\n"
            "[yellow]请检查服务是否运行，或切换到其他 Provider（菜单 8）[/]",
            title="[red]服务离线[/]", border_style="red", box=box.ROUNDED))

    # 自动加载上下文文件并展示
    work_dir = os.getcwd()
    contexts = discover_context_files(work_dir)
    try:
        models = api.list_models()
        run = api.running_models() if api.provider.type == "ollama" else []
        online_mark = "[green][*][/]"
    except Exception:
        online_mark = "[red][X][/]"

    info_parts = [f"{online_mark} [bold]{prov.name}[/]"]
    info_parts.append(f"[dim]|[/]  可用 [bold cyan]{len(models)}[/] 个模型")
    if contexts:
        info_parts.append(f"[dim]|[/]  上下文 [cyan]{len(contexts)}[/] 个文件")
    console.print("  ".join(info_parts))

    if contexts:
        console.print(f"[dim]  上下文:[/] {summarize_contexts(contexts)}")

    menu = (
        "  [bold yellow]1[/]  [chat]  与模型对话\n"
        "  [bold yellow]2[/]  [hist] 恢复历史会话\n"
        "  [bold yellow]3[/]  [list]  列出所有可用模型\n"
        "  [bold yellow]4[/]  [info]  查看模型详情\n"
        "  [bold yellow]5[/]  [gen]   单次生成\n"
        "  [bold yellow]6[/]  [run]   查看已加载模型\n"
        "  [bold yellow]7[/]  [dl]    拉取新模型\n"
        "  [bold yellow]8[/]  [del]   删除模型\n"
        "  [bold yellow]9[/]  [tool]  工具系统\n"
        "  [bold yellow]0[/]  [cfg]   管理 Provider\n"
        "  [bold yellow]q[/]  [exit]  退出"
    )
    while True:
        console.print()
        console.print(Panel(menu,
            title=f"[bold]主菜单[/]  [dim][{prov.type}] {prov.name}[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见[/]")
            break

        if choice in ("0", "q", "quit", "exit"):
            console.print("[dim]再见[/]")
            break
        elif choice == "1":
            model = _pick_model(api, "选择对话模型")
            if model:
                cmd_chat(api, model, None, 0.7, False, cwd=work_dir)
        elif choice == "2":
            sid = _pick_session()
            if sid:
                session = _session_store.get_session(sid)
                if session:
                    model = _pick_model(api, f"选择该会话的模型 (原: {session.model})")
                    if model:
                        cmd_chat(api, model, None, 0.7, False,
                                session_id=sid, cwd=work_dir)
            else:
                model = _pick_model(api, "选择对话模型")
                if model:
                    cmd_chat(api, model, None, 0.7, False, cwd=work_dir)
        elif choice == "3":
            cmd_list(api)
        elif choice == "4":
            model = _pick_model(api, "选择查看的模型")
            if model:
                cmd_info(api, model)
        elif choice == "5":
            model = _pick_model(api, "选择生成模型")
            if model:
                prompt = console.input("[cyan]输入提示词:[/] ").strip()
                if prompt:
                    cmd_generate(api, model, prompt, 0.7, cwd=work_dir)
        elif choice == "6":
            cmd_running(api)
        elif choice == "7":
            name = console.input("[cyan]输入要拉取的模型名 (如 llama3:8b):[/] ").strip()
            if name:
                cmd_pull(api, name)
        elif choice == "8":
            model = _pick_model(api, "选择要删除的模型")
            if model:
                confirm = console.input(
                    f"[red]确认删除 {model}? (y/N):[/] ").strip().lower()
                if confirm == "y":
                    cmd_delete(api, model)
        elif choice == "9":
            tool_menu(api)
        elif choice == "cfg":
            cfg_menu(api, cfg)
        else:
            console.print("[yellow]无效选择，请输入 0-9[/]")


def tool_menu(api: YukiAPI):
    sub = (
        "  [bold yellow]1[/]  列出所有工具\n"
        "  [bold yellow]2[/]  执行工具\n"
        "  [bold yellow]3[/]  查看上下文文件\n"
        "  [bold yellow]0[/]  返回"
    )
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]工具系统[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if choice == "0":
            break
        elif choice == "1":
            cmd_tools(_tool_registry)
        elif choice == "2":
            name = console.input("[cyan]工具名称:[/] ").strip()
            if name:
                params_str = console.input("[cyan]参数 (JSON, 空为 {}):[/] ").strip() or "{}"
                cmd_tools_exec(name, params_str, _tool_registry)
        elif choice == "3":
            work_dir = os.getcwd()
            contexts = discover_context_files(work_dir)
            if contexts:
                console.print(f"[dim]当前目录上下文文件:[/]")
                console.print(summarize_contexts(contexts))
                for ctx in contexts:
                    console.print(Panel(
                        f"[green]{ctx.source}[/]  [dim]{len(ctx.content)} 字[/]",
                        title="[cyan]内容预览[/]", border_style="cyan",
                        box=box.ROUNDED, expand=False))
            else:
                console.print("[dim]未发现上下文规范文件[/]")


def cfg_menu(api: YukiAPI, cfg):
    sub = (
        "  [bold yellow]a[/]  查看所有 Provider\n"
        "  [bold yellow]b[/]  添加 Provider\n"
        "  [bold yellow]c[/]  重命名 Provider\n"
        "  [bold yellow]d[/]  删除 Provider\n"
        "  [bold yellow]e[/]  查看用量统计\n"
        "  [bold yellow]0[/]  返回"
    )
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]Provider 管理[/]",
            border_style="blue", box=box.ROUNDED, expand=False))
        try:
            choice = console.input("[cyan]>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if choice == "0":
            break
        elif choice == "a":
            cmd_config_list()
        elif choice == "b":
            name = console.input("Provider 名称 (唯一标识): ").strip()
            ptype = console.input(
                "类型 [ollama/openai/custom] (默认 ollama): ").strip() or "ollama"
            url = console.input(
                "API 地址 (如 https://api.groq.com/openai/v1): ").strip()
            api_key = console.input("API Key (可选，直接回车): ").strip()
            default_model = console.input("默认模型 (可选): ").strip()
            timeout_str = console.input("超时秒数 (默认 120): ").strip()
            timeout = int(timeout_str) if timeout_str.isdigit() else 120
            cmd_config_add(name, ptype, url, api_key, default_model, timeout)
        elif choice == "c":
            old = console.input("原名称: ").strip()
            new = console.input("新名称: ").strip()
            cmd_config_rename(old, new)
        elif choice == "d":
            name = console.input("要删除的 Provider 名称: ").strip()
            confirm = console.input(
                f"[red]确认删除 {name}? (y/N):[/] ").strip().lower()
            if confirm == "y":
                cmd_config_remove(name)
        elif choice == "e":
            cmd_usage_summary()


# ---- 主入口 ----

def main():
    parser = argparse.ArgumentParser(
        description="Yuki Code — 多 Provider AI 代码助手，支持 Ollama / OpenAI / 自定义",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python -m cli              # 交互式菜单（直接运行即用）
  yuki status                # 查看当前 Provider 状态
  yuki list                  # 列出可用模型
  yuki chat qwen3:8b        # 交互式对话
  yuki chat qwen3:8b --stdin # 管道模式对话
  yuki generate qwen3:8b -p "解释量子计算"

会话历史:
  yuki sessions              # 列出历史会话
  yuki chat qwen3:8b --session <id>

上下文感知:
  在项目根目录放置 CLAUDE.md、.cursorrules 等文件，
  Yuki Code 会自动加载作为上下文。

工具系统:
  yuki tools                # 列出所有可用工具
  yuki tool grep --pattern "TODO" --path .

Provider 管理:
  yuki config list
  yuki config add --name groq --type openai --url https://api.groq.com/openai/v1 --api-key sk-xxx

直接指定 Provider:
  yuki --provider groq chat llama-3.3-70b-versatile
""")
    parser.add_argument("--provider", help="使用指定名称的 Provider")
    parser.add_argument("--url", help="直接指定 API 地址（临时）")
    parser.add_argument("--api-key", help="API Key（配合 --url）")
    parser.add_argument("--timeout", type=int, default=120)

    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="查看当前 Provider 状态")

    # list
    sub.add_parser("list", help="列出可用模型")

    # sessions
    sub.add_parser("sessions", help="列出历史会话")

    # usage
    sub.add_parser("usage", help="查看 Token 用量统计")

    # info
    info_p = sub.add_parser("info", help="查看模型详情")
    info_p.add_argument("model", help="模型名称")

    # pull
    pull_p = sub.add_parser("pull", help="拉取模型")
    pull_p.add_argument("model", help="模型名称")

    # delete
    del_p = sub.add_parser("delete", help="删除模型")
    del_p.add_argument("model", help="模型名称")

    # chat
    chat_p = sub.add_parser("chat", help="交互式对话")
    chat_p.add_argument("model", help="模型名称")
    chat_p.add_argument("--system", help="系统提示词")
    chat_p.add_argument("--temp", type=float, default=0.7)
    chat_p.add_argument("--stdin", action="store_true")
    chat_p.add_argument("--session", dest="session_id", help="指定会话 ID 恢复")
    chat_p.add_argument("--cwd", dest="cwd", help="工作目录（用于上下文感知）")

    # generate
    gen_p = sub.add_parser("generate", help="单次生成")
    gen_p.add_argument("model", help="模型名称")
    gen_p.add_argument("--prompt", "-p", required=True)
    gen_p.add_argument("--temp", type=float, default=0.7)
    gen_p.add_argument("--cwd", dest="cwd", help="工作目录")

    # running
    sub.add_parser("running", help="查看已加载模型")

    # tools
    tools_p = sub.add_parser("tools", help="列出所有工具")

    # tool exec
    tool_p = sub.add_parser("tool", help="执行工具")
    tool_p.add_argument("name", help="工具名称")
    tool_p.add_argument("params", nargs="?", default="{}",
                        help="参数 (JSON 格式)")

    # config
    cfg_sub = sub.add_parser("config", help="Provider 管理")
    cfg_subsub = cfg_sub.add_subparsers(dest="config_cmd")

    cfg_list_p = cfg_subsub.add_parser("list", help="列出所有 Provider")
    cfg_add_p = cfg_subsub.add_parser("add", help="添加 Provider")
    cfg_add_p.add_argument("--name", required=True)
    cfg_add_p.add_argument("--type", required=True,
                           choices=["ollama", "openai", "custom"])
    cfg_add_p.add_argument("--url", required=True)
    cfg_add_p.add_argument("--api-key", default="")
    cfg_add_p.add_argument("--default-model", default="")
    cfg_add_p.add_argument("--timeout", type=int, default=120)
    cfg_add_p.add_argument("--label", default="",
                           help="显示名称（默认同 --name）")

    cfg_remove_p = cfg_subsub.add_parser("remove", help="删除 Provider")
    cfg_remove_p.add_argument("--name", required=True)
    cfg_rename_p = cfg_subsub.add_parser("rename", help="重命名 Provider")
    cfg_rename_p.add_argument("--old", required=True)
    cfg_rename_p.add_argument("--new", required=True)

    args = parser.parse_args()

    # config 子命令直接处理
    if args.command == "config":
        match args.config_cmd:
            case "list":
                cmd_config_list()
            case "add":
                label = args.label or args.name
                prov = Provider(type=args.type, name=label, base_url=args.url,
                                api_key=args.api_key,
                                default_model=args.default_model,
                                timeout=args.timeout, label=args.type)
                add(args.name, prov)
                console.print(
                    f"[green][OK][/] 已添加: {args.name}  [{args.type}]  {args.url}")
            case "remove":
                cmd_config_remove(args.name)
            case "rename":
                cmd_config_rename(args.old, args.new)
            case _:
                cmd_config_list()
        sys.exit(0)

    # 快捷子命令（无需创建 API）
    if args.command == "sessions":
        cmd_sessions()
        sys.exit(0)
    if args.command == "usage":
        cmd_usage_summary()
        sys.exit(0)
    if args.command == "tools":
        cmd_tools(_tool_registry)
        sys.exit(0)
    if args.command == "tool":
        cmd_tools_exec(args.name, args.params, _tool_registry)
        sys.exit(0)

    # 需要 API 的命令
    api = _make_api(args)
    work_dir = getattr(args, "cwd", None) or os.getcwd()

    match args.command:
        case "status":
            cmd_status(api, args.provider or "")
        case "list":
            cmd_list(api)
        case "info":
            cmd_info(api, args.model)
        case "pull":
            cmd_pull(api, args.model)
        case "delete":
            cmd_delete(api, args.model)
        case "chat":
            cmd_chat(api, args.model, args.system, args.temp,
                    args.stdin, args.session_id, work_dir)
        case "generate":
            cmd_generate(api, args.model, args.prompt, args.temp, work_dir)
        case "running":
            cmd_running(api)
        case None:
            interactive(args)
