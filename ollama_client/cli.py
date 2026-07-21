"""CLI 命令行界面"""

import sys
import argparse
import io
from .api import OllamaAPI, DEFAULT_BASE_URL
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich.spinner import Spinner
from rich import print as rprint
import json

# 解决 Windows GBK 控制台 Unicode 输出问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

console = Console(legacy_windows=False, force_terminal=True)


def cmd_status(api: OllamaAPI):
    """状态检测"""
    if api.ping():
        lines = [f"[green]●[/] 服务在线   [dim]{api.base_url}[/]"]
        try:
            models = api.list_models()
            running = api.running_models()
            lines.append(f"[green]●[/] 本地模型   [bold cyan]{len(models)}[/] 个")
            lines.append(f"[green]●[/] 已加载     [bold cyan]{len(running)}[/] 个")
        except Exception as e:
            lines.append(f"[yellow]⚠[/] 模型列表获取失败: {e}")
        console.print(
            Panel(
                "\n".join(lines),
                title="[bold green]Ollama 状态[/]",
                border_style="green",
                box=box.ROUNDED,
                expand=False,
            )
        )
    else:
        console.print(
            Panel(
                f"[red]✗ 服务未启动[/]\n[dim]请先运行 [bold]ollama serve[/][/]",
                title="[red]Ollama 状态[/]",
                border_style="red",
                box=box.ROUNDED,
                expand=False,
            )
        )
        sys.exit(1)


def cmd_list(api: OllamaAPI):
    """列出所有模型"""
    try:
        models = api.list_models()
    except Exception as e:
        console.print(f"[red][X][/] 获取模型列表失败: {e}")
        sys.exit(1)

    if not models:
        console.print("[yellow]未检测到任何本地模型，运行 [bold]ollama pull <model>[/] 拉取")
        return

    table = Table(
        title="[bold cyan]📋 本地模型列表[/]",
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
        border_style="cyan",
    )
    table.add_column("#", style="bold yellow", width=4, justify="center")
    table.add_column("模型名称", style="bold green")
    table.add_column("大小", justify="right", style="cyan")
    table.add_column("最后修改", style="dim")
    table.add_column("Digest", style="dim")

    for i, m in enumerate(models, 1):
        size = api.format_size(m.size)
        mod = m.modified[:19].replace("T", " ") if m.modified else "-"
        table.add_row(str(i), m.name, size, mod, m.digest[:12] + "...")

    console.print(table)


def cmd_info(api: OllamaAPI, name: str):
    """查看模型详情"""
    try:
        info = api.show_model_info(name)
        console.rule(f"[bold]模型信息: {name}")
        for key, val in info.items():
            if isinstance(val, str) and len(val) > 200:
                val = val[:200] + "..."
            console.print(f"[cyan]{key}:[/] {val}")
    except Exception as e:
        console.print(f"[red][X][/] 获取模型信息失败: {e}")
        sys.exit(1)


def cmd_pull(api: OllamaAPI, name: str):
    """拉取模型"""
    console.print(f"[cyan]开始拉取模型:[/] {name} ...")
    try:
        for status in api.pull_model(name):
            console.print(f"  {status}")
        console.print("[green][OK][/] 拉取完成")
    except Exception as e:
        console.print(f"[red][X][/] 拉取失败: {e}")
        sys.exit(1)


def cmd_delete(api: OllamaAPI, name: str):
    """删除模型"""
    if api.delete_model(name):
        console.print(f"[green][OK][/] 已删除模型: {name}")
    else:
        console.print(f"[red][X][/] 删除失败: {name}")
        sys.exit(1)


def _strip_think_tags(text: str) -> str:
    """安全网：剥离回答文本中可能残留的 <think> 标签"""
    while "<think>" in text:
        i = text.find("<think>")
        j = text.find("</think>", i)
        if j == -1:
            text = text[:i] + text[i + len("<think>"):]
        else:
            text = text[:i] + text[j + len("</think>"):]
    return text


def _build_window(thinking_text: str, answer_text: str, thinking_done: bool) -> Group:
    """构建 GUI 风格窗口：思考卡片 + 分隔 + 回答卡片，两张独立卡片"""
    cards = []
    if thinking_text.strip():
        status = "[dim italic]思考中…[/]" if not thinking_done else "[dim]完成[/]"
        body = Text(thinking_text, style="dim", overflow="fold", no_wrap=False)
        cards.append(
            Panel(
                body,
                title="[bold yellow]💡 推理过程[/]",
                title_align="left",
                subtitle=status,
                subtitle_align="right",
                border_style="yellow",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    if answer_text.strip():
        answer_text = _strip_think_tags(answer_text)
        body = Text(answer_text, style="white", overflow="fold", no_wrap=False)
        cards.append(
            Panel(
                body,
                title="[bold green]✨ 回答[/]",
                title_align="left",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    if not cards:
        cards.append(
            Panel(
                Align.center(Spinner("dots", text="模型正在生成…"), vertical="middle"),
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    return Group(*cards)


def _stream_and_render(stream, title: str = "") -> str:
    """
    GUI 风格流式渲染：思考与回答分别呈现在两张独立卡片中，绝不混排。
    兼容独立 thinking 字段 与 content 内嵌 <think> 标签。
    返回正式回答文本。
    """
    thinking_buf = ""
    answer_buf = ""
    in_thinking = False      # 当前片段是否处于思考段
    thinking_done = False    # 思考是否已结束
    finished = False

    header = (
        Panel(
            Align.center(f"[bold cyan]{title}[/]" if title else "[bold cyan]Ollama[/]"),
            border_style="bright_blue",
            box=box.DOUBLE,
            padding=(0, 1),
            expand=True,
        )
        if title
        else None
    )

    def render():
        grp = _build_window(thinking_buf, answer_buf, thinking_done)
        return Group(header, grp) if header else grp

    with Live(render(), console=console, refresh_per_second=12, transient=False) as live:
        for kind, text in stream:
            if finished:
                break
            if kind == "thinking":
                # 独立 thinking 字段（qwen3 等）：直接进思考卡，不影响 content 解析
                thinking_buf += text
            else:  # content
                # 仅解析 content 内嵌的 <think> 标签（deepseek 等）；
                # 与上面独立 thinking 字段互不干扰
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
    # Live 结束后把最终内容永久打印到屏幕
    console.print(render())
    return answer_buf


def cmd_chat(api: OllamaAPI, model: str, system: str | None, temp: float, stdin: bool):
    """交互式对话"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
        console.print(f"[dim]System:[/] {system}")

    console.print()
    console.rule(f"[bold green]💬 对话中[/] [cyan]{model}[/]")
    console.print("[dim]指令: /quit 退出 | /clear 清空上下文 | /models 看模型[/]\n")

    if stdin:
        # 管道模式：读取标准输入作为用户消息
        content = sys.stdin.read()
        messages.append({"role": "user", "content": content})
        response = _stream_and_render(
            api.chat(model, messages, temperature=temp, stream=True), title=model
        )
        return

    # 交互模式
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
                api.chat(model, messages, temperature=temp, stream=True), title=model
            )
        except KeyboardInterrupt:
            print()
            console.print("[yellow]已中断生成[/]")
            messages.append({"role": "assistant", "content": response})
            break
        messages.append({"role": "assistant", "content": response})
        console.print()


def cmd_generate(api: OllamaAPI, model: str, prompt: str, temp: float):
    """单次生成"""
    console.print()
    console.rule(f"[bold cyan]🧠 生成[/] [green]{model}[/]")
    console.print(f"[dim]提示词:[/] {prompt}\n")
    try:
        _stream_and_render(
            api.generate(model, prompt, temperature=temp, stream=True), title=model
        )
    except Exception as e:
        console.print(f"\n[red]生成失败: {e}[/]")
        sys.exit(1)


def cmd_running(api: OllamaAPI):
    """查看当前加载的模型"""
    try:
        models = api.running_models()
    except Exception as e:
        console.print(f"[red][X][/] 获取失败: {e}")
        sys.exit(1)

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
        dur_str = f"{dur:.1f}s" if dur else "-"
        table.add_row(m.get("name", "-"), size, dur_str)

    console.print(table)


def _pick_model(api: OllamaAPI, prompt_text: str = "选择模型序号") -> str | None:
    """列出模型并让用户选择，返回模型名"""
    try:
        models = api.list_models()
    except Exception as e:
        console.print(f"[red][X][/] 获取模型列表失败: {e}")
        return None
    if not models:
        console.print("[yellow]未检测到任何本地模型，请先拉取模型[/]")
        return None

    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", style="bold yellow", width=4)
    table.add_column("模型名称", style="green")
    table.add_column("大小", justify="right")
    for i, m in enumerate(models, 1):
        table.add_row(str(i), m.name, api.format_size(m.size))
    console.print(table)

    while True:
        choice = console.input(f"[cyan]{prompt_text} (1-{len(models)}, 回车取消):[/] ").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1].name
        console.print("[yellow]输入无效，请重新选择[/]")


def interactive(api: OllamaAPI):
    """交互式主界面 —— 运行即用，无需记命令"""
    console.print()
    console.print(
        Panel(
            "[bold cyan]Ollama Client[/]\n[dim]本地大模型对接工具[/]",
            box=box.DOUBLE,
            border_style="cyan",
            padding=(0, 4),
            expand=False,
        )
    )

    # 启动自动检测服务
    if not api.ping():
        console.print(
            Panel(
                f"[red]✗ 未检测到 Ollama 服务[/]\n[dim]{api.base_url}[/]\n\n"
                "[yellow]请先启动 Ollama：运行 [bold]ollama serve[/] 或打开 Ollama 应用[/]",
                title="[red]服务离线[/]",
                border_style="red",
                box=box.ROUNDED,
            )
        )
        return
    try:
        model_count = len(api.list_models())
        run_count = len(api.running_models())
        console.print(
            f"[green]●[/] 服务在线   [dim]|[/]   本地模型 [bold cyan]{model_count}[/] 个"
            f"   [dim]|[/]   已加载 [bold cyan]{run_count}[/] 个"
        )
    except Exception:
        console.print("[green]●[/] 服务在线")

    menu = (
        "  [bold yellow]1[/]  💬  与模型对话\n"
        "  [bold yellow]2[/]  📋  列出所有本地模型\n"
        "  [bold yellow]3[/]  🔍  查看模型详情\n"
        "  [bold yellow]4[/]  🧠  单次生成\n"
        "  [bold yellow]5[/]  ⚡  查看当前加载的模型\n"
        "  [bold yellow]6[/]  ⬇️   拉取新模型\n"
        "  [bold yellow]7[/]  🗑️   删除模型\n"
        "  [bold yellow]0[/]  🚪  退出"
    )
    while True:
        console.print()
        console.print(
            Panel(menu, title="[bold]主菜单[/]", border_style="blue", box=box.ROUNDED, expand=False)
        )
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
        else:
            console.print("[yellow]无效选择，请输入 0-7[/]")


def main():
    parser = argparse.ArgumentParser(
        description="Ollama 本地模型对接 CLI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s status              检测 Ollama 服务状态
  %(prog)s list                列出所有本地模型
  %(prog)s info qwen2.5-coder:7b   查看模型详情
  %(prog)s chat qwen3:8b       交互式对话
  %(prog)s chat qwen3:8b --stdin  管道模式对话
  %(prog)s generate qwen3:8b --prompt "解释量子计算"  单次生成
  %(prog)s pull llama3:8b      拉取模型
  %(prog)s running             查看当前加载的模型
        """,
    )
    parser.add_argument(
        "--url", default=DEFAULT_BASE_URL, help=f"Ollama API 地址 (默认: {DEFAULT_BASE_URL})"
    )
    parser.add_argument(
        "--timeout", type=int, default=120, help="请求超时秒数 (默认: 120)"
    )

    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="检测 Ollama 服务状态")

    # list
    sub.add_parser("list", help="列出所有本地模型")

    # info
    info_p = sub.add_parser("info", help="查看模型详情")
    info_p.add_argument("model", help="模型名称 (如 qwen3:8b)")

    # pull
    pull_p = sub.add_parser("pull", help="拉取模型")
    pull_p.add_argument("model", help="模型名称 (如 llama3:8b)")

    # delete
    del_p = sub.add_parser("delete", help="删除模型")
    del_p.add_argument("model", help="模型名称")

    # chat
    chat_p = sub.add_parser("chat", help="交互式对话")
    chat_p.add_argument("model", help="模型名称 (如 qwen3:8b)")
    chat_p.add_argument("--system", help="系统提示词")
    chat_p.add_argument("--temp", type=float, default=0.7, help="Temperature (默认: 0.7)")
    chat_p.add_argument(
        "--stdin", action="store_true", help="从标准输入读取用户消息 (管道模式)"
    )

    # generate
    gen_p = sub.add_parser("generate", help="单次生成")
    gen_p.add_argument("model", help="模型名称")
    gen_p.add_argument("--prompt", "-p", required=True, help="提示词")
    gen_p.add_argument("--temp", type=float, default=0.7, help="Temperature (默认: 0.7)")

    # running
    sub.add_parser("running", help="查看当前加载的模型")

    args = parser.parse_args()

    api = OllamaAPI(base_url=args.url, timeout=args.timeout)

    # 不带子命令时进入交互式主界面（运行即用）
    if not args.command:
        try:
            interactive(api)
        except KeyboardInterrupt:
            console.print("\n[dim]再见[/]")
        sys.exit(0)

    # 命令路由
    match args.command:
        case "status":
            cmd_status(api)
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
