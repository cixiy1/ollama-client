"""CLI 命令行界面"""
from __future__ import annotations

import sys
import argparse
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.align import Align
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text

from .api import YukiAPI
from .config import load, save, add, remove, rename, use, get_current, Provider, CONFIG_FILE

console = Console()


# ---- 思考标签清理 ----

def _strip_think_tags(text: str) -> str:
    while "<think>" in text:
        i = text.find("<think>")
        j = text.find("</think>", i)
        if j == -1:
            text = text[:i] + text[i + len("<think>"):]
        else:
            text = text[:i] + text[j + len("</think>"):]
    return text


# ---- 流式渲染 ----

def _build_window(thinking_text: str, answer_text: str, thinking_done: bool) -> Group:
    cards = []
    if thinking_text.strip():
        status = "[dim italic]思考中…[/]" if not thinking_done else "[dim]完成[/]"
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
            title="[bold green]✨ 回答[/]",
            title_align="left",
            border_style="green",
            box=box.ROUNDED,
            padding=(1, 2)))
    if not cards:
        cards.append(Panel(
            Align.center(Spinner("dots", text="模型正在生成…"), vertical="middle"),
            border_style="cyan", box=box.ROUNDED, padding=(1, 2)))
    return Group(*cards)


def _stream_and_render(stream, title: str = "") -> str:
    thinking_buf = ""
    answer_buf = ""
    in_thinking = False
    thinking_done = False
    finished = False

    header = (Panel(
        Align.center(f"[bold cyan]{title}[/]" if title else "[bold cyan]Yuki Code[/]"),
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
                            text = text[idx + len("<think>"):]
                            in_thinking = True
                    else:
                        idx = text.find("</think>")
                        if idx == -1:
                            thinking_buf += text
                            text = ""
                        else:
                            thinking_buf += text[:idx]
                            text = text[idx + len("</think>"):]
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
            console.print(f"[red]未找到 Provider: {args.provider}[/]  (使用 --url 参数指定，或先 yuki config add)[/]")
            sys.exit(1)
    elif args.url:
        # 临时用 --url，创建匿名 Provider
        prov = Provider(type="custom", name=args.url, base_url=args.url, timeout=args.timeout)
    else:
        prov = get_current()
        if not prov:
            console.print("[red]未配置任何 Provider，请先运行 yuki config add 或 --url[/]")
            sys.exit(1)
    return YukiAPI(prov)


# ---- 命令实现 ----

def cmd_status(api: YukiAPI, provider_name: str):
    try:
        online = api.ping()
    except Exception:
        online = False
    if online:
        console.print(f"[green][*][/] 服务在线   [dim]{api.provider.base_url}[/]   "
                       f"[dim]|[/]   [{api.provider.type}] {api.provider.name}")
    else:
        console.print(f"[red][X][/] 服务离线   [dim]{api.provider.base_url}[/]   "
                       f"[dim]|[/]   [{api.provider.type}] {api.provider.name}")
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
    console.print(f"[cyan]开始拉取 {name}…[/]  (Ctrl+C 中断)\n")
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


def cmd_chat(api: YukiAPI, model: str, system: str | None, temp: float, stdin: bool):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
        console.print(f"[dim]System:[/] {system}")
    console.print()
    console.rule(f"[bold green][chat] 对话中[/]  [cyan]{model}[/]")
    console.print("[dim]指令: /quit 退出 | /clear 清空上下文 | /models 看模型[/]\n")

    if stdin:
        content = sys.stdin.read()
        messages.append({"role": "user", "content": content})
        _stream_and_render(api.chat(model, messages, temperature=temp, stream=True), title=model)
        return

    while True:
        try:
            user_input = console.input("[cyan]You:[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]退出对话[/]")
            break
        if user_input in ("/quit", "/exit", "quit", "exit"):
            console.print("[dim]退出对话[/]")
            break
        if user_input == "/clear":
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            console.print("[dim]对话历史已清除[/]")
            continue
        if user_input == "/models":
            cmd_list(api)
            continue
        if not user_input:
            continue
        messages.append({"role": "user", "content": user_input})
        console.print()
        response = ""
        try:
            response = _stream_and_render(
                api.chat(model, messages, temperature=temp, stream=True), title=model)
        except KeyboardInterrupt:
            print()
            console.print("[yellow]已中断生成[/]")
            messages.append({"role": "assistant", "content": response})
            break
        messages.append({"role": "assistant", "content": response})
        console.print()


def cmd_generate(api: YukiAPI, model: str, prompt: str, temp: float):
    console.print()
    console.rule(f"[bold cyan][gen] 生成[/]  [green]{model}[/]")
    console.print(f"[dim]提示词:[/] {prompt}\n")
    try:
        _stream_and_render(
            api.generate(model, prompt, temperature=temp, stream=True), title=model)
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


def cmd_config_add(name: str, ptype: str, url: str, api_key: str, default_model: str, timeout: int):
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
        console.print(f"[red]重命名失败（'{old}' 不存在或 '{new}' 已占用）[/]")


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
        choice = console.input(f"[cyan]{prompt_text} (1-{len(models)}, 回车取消):[/] ").strip()
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
        choice = console.input(f"[cyan]{prompt_text} (1-{len(items)}, 回车取消):[/] ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1][0]
        console.print("[yellow]输入无效[/]")


def interactive(args):
    cfg = load()
    prov = get_current()

    console.print()
    console.print(Panel(
        "[bold cyan]Yuki Code[/]\n[dim]多 Provider AI 代码助手[/]",
        box=box.DOUBLE, border_style="cyan", padding=(0, 4), expand=False))

    # 无任何 Provider 时引导添加
    if not cfg.providers:
        console.print(Panel(
            "[yellow]未配置任何 Provider[/]\n\n"
            "请先添加一个 Provider：\n"
            "  [cyan]yuki config add --name ollama --type ollama --url http://localhost:11434[/]\n\n"
            "或使用 --url 直接运行：\n"
            "  [cyan]yuki --url https://api.groq.com chat <model> --api-key sk-xxx[/]",
            title="[bold]欢迎[/]", border_style="yellow", box=box.ROUNDED))
        return

    api = YukiAPI(prov)

    if not api.ping():
        console.print(Panel(
            f"[red][X] 无法连接 {api.provider.base_url}[/]\n"
            f"[dim]类型: {api.provider.type} | {api.provider.name}[/]\n\n"
            "[yellow]请检查服务是否运行，或切换到其他 Provider（菜单 8）[/]",
            title="[red]服务离线[/]", border_style="red", box=box.ROUNDED))

    # Provider 信息行
    try:
        models = api.list_models()
        run = api.running_models() if api.provider.type == "ollama" else []
        console.print(
            f"[green][*][/] {api.provider.name}  [dim]|[/]  "
            f"可用模型 [bold cyan]{len(models)}[/] 个"
            + (f"  [dim]|[/]  已加载 [bold cyan]{len(run)}[/] 个" if run else ""))
    except Exception:
        console.print(f"[green][*][/] {api.provider.name}  [dim]{api.provider.base_url}[/]")

    menu = (
        "  [bold yellow]1[/]  [chat]  与模型对话\n"
        "  [bold yellow]2[/]  [list]  列出所有可用模型\n"
        "  [bold yellow]3[/]  [info]  查看模型详情\n"
        "  [bold yellow]4[/]  [gen]  单次生成\n"
        "  [bold yellow]5[/]  [run]  查看已加载模型\n"
        "  [bold yellow]6[/]  [dl]   拉取新模型\n"
        "  [bold yellow]7[/]  [del]   删除模型\n"
        "  [bold yellow]8[/]  [sw]  切换 Provider\n"
        "  [bold yellow]9[/]  [cfg]   管理 Provider\n"
        "  [bold yellow]0[/]  [exit]  退出"
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
                cmd_chat(api, model, None, 0.7, False)
        elif choice == "2":
            cmd_list(api)
        elif choice == "3":
            model = _pick_model(api, "选择查看的模型")
            if model:
                cmd_info(api, model)
        elif choice == "4":
            model = _pick_model(api, "选择生成模型")
            if model:
                prompt = console.input("[cyan]输入提示词:[/] ").strip()
                if prompt:
                    cmd_generate(api, model, prompt, 0.7)
        elif choice == "5":
            cmd_running(api)
        elif choice == "6":
            name = console.input("[cyan]输入要拉取的模型名 (如 llama3:8b):[/] ").strip()
            if name:
                cmd_pull(api, name)
        elif choice == "7":
            model = _pick_model(api, "选择要删除的模型")
            if model:
                confirm = console.input(f"[red]确认删除 {model}? (y/N):[/] ").strip().lower()
                if confirm == "y":
                    cmd_delete(api, model)
        elif choice == "8":
            new_key = _pick_provider("选择要切换的 Provider")
            if new_key:
                p = use(new_key)
                if p:
                    prov = p
                    api = YukiAPI(prov)
                    console.print(f"[green][OK][/] 已切换到 [{p.type}] {p.name}")
        elif choice == "9":
            cfg_menu(api, cfg)
        else:
            console.print("[yellow]无效选择，请输入 0-9[/]")


def cfg_menu(api: YukiAPI, cfg):
    sub = (
        "  [bold yellow]a[/]  查看所有 Provider\n"
        "  [bold yellow]b[/]  添加 Provider\n"
        "  [bold yellow]c[/]  重命名 Provider\n"
        "  [bold yellow]d[/]  删除 Provider\n"
        "  [bold yellow]0[/]  返回"
    )
    while True:
        console.print()
        console.print(Panel(sub, title="[bold]Provider 管理[/]", border_style="blue", box=box.ROUNDED, expand=False))
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
            ptype = console.input("类型 [ollama/openai/custom] (默认 ollama): ").strip() or "ollama"
            url = console.input("API 地址 (如 https://api.groq.com/openai/v1): ").strip()
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
            confirm = console.input(f"[red]确认删除 {name}? (y/N):[/] ").strip().lower()
            if confirm == "y":
                cmd_config_remove(name)


# ---- 主入口 ----

def main():
    parser = argparse.ArgumentParser(
        description="Yuki Code — 本地 AI 代码助手，支持 Ollama / OpenAI 兼容接口 / 自定义 Provider",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  yuki                          # 交互式菜单（运行即用）
  yuki status                   # 查看当前 Provider 状态
  yuki list                     # 列出可用模型
  yuki chat qwen3:8b            # 交互式对话
  yuki chat qwen3:8b --stdin    # 管道模式对话
  yuki generate qwen3:8b -p "解释量子计算"  # 单次生成

Provider 管理:
  yuki config list              # 查看所有 Provider
  yuki config add --name groq --type openai --url https://api.groq.com/openai/v1 --api-key sk-xxx
  yuki config remove --name groq
  yuki config rename --old ollama --new local

直接指定 Provider:
  yuki --provider groq chat llama-3.3-70b-versatile
  yuki --url https://api.example.com chat gpt-4o --api-key sk-xxx
""")
    parser.add_argument("--provider", help="使用指定名称的 Provider（需先 config add）")
    parser.add_argument("--url", help="直接指定 API 地址（临时，不保存）")
    parser.add_argument("--api-key", help="API Key（配合 --url 使用）")
    parser.add_argument("--timeout", type=int, default=120, help="请求超时秒数 (默认: 120)")

    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="查看当前 Provider 状态")

    # list
    sub.add_parser("list", help="列出可用模型")

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
    chat_p.add_argument("--stdin", action="store_true", help="从标准输入读取")

    # generate
    gen_p = sub.add_parser("generate", help="单次生成")
    gen_p.add_argument("model", help="模型名称")
    gen_p.add_argument("--prompt", "-p", required=True)
    gen_p.add_argument("--temp", type=float, default=0.7)

    # running
    sub.add_parser("running", help="查看已加载模型")

    # config
    cfg_sub = sub.add_parser("config", help="Provider 管理")
    cfg_subsub = cfg_sub.add_subparsers(dest="config_cmd")

    cfg_list_p = cfg_subsub.add_parser("list", help="列出所有 Provider")
    cfg_add_p = cfg_subsub.add_parser("add", help="添加 Provider")
    cfg_add_p.add_argument("--name", required=True, help="Provider 名称（唯一标识）")
    cfg_add_p.add_argument("--type", required=True, choices=["ollama","openai","custom"],
                           help="类型: ollama | openai | custom")
    cfg_add_p.add_argument("--url", required=True, help="API 根地址")
    cfg_add_p.add_argument("--api-key", default="", help="API Key")
    cfg_add_p.add_argument("--default-model", default="", help="默认模型")
    cfg_add_p.add_argument("--timeout", type=int, default=120)
    cfg_add_p.add_argument("--label", dest="label", default="",
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
                                api_key=args.api_key, default_model=args.default_model,
                                timeout=args.timeout)
                add(args.name, prov)
                console.print(f"[green][OK][/] 已添加: {args.name}  [{args.type}]  {args.url}")
            case "remove":
                cmd_config_remove(args.name)
            case "rename":
                cmd_config_rename(args.old, args.new)
            case _:
                cmd_config_list()
        sys.exit(0)

    # 非 config 命令走统一 API 创建逻辑
    api = _make_api(args)

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
            cmd_chat(api, args.model, args.system, args.temp, args.stdin)
        case "generate":
            cmd_generate(api, args.model, args.prompt, args.temp)
        case "running":
            cmd_running(api)
        case None:
            interactive(args)
