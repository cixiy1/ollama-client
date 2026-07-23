"""Plan Mode — 只读分析 + 生成执行计划"""
from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text
from rich import box

from .config import load as load_config
from .api import YukiAPI, Provider
from .context import load_context_for_directory, discover_context_files, summarize_contexts

console = Console()


PLAN_SYSTEM_PROMPT = """\
你是一个高级代码分析助手。用户会给你一个任务，你的职责是：

1. **深度分析**：理解项目结构、技术栈、现有代码风格
2. **识别关键文件**：哪些文件需要修改、创建、删除
3. **制定计划**：用 Markdown 列出具体的修改步骤
4. **预估风险**：标注可能的副作用或需要注意的点

**严格禁止**：
- 不要写任何代码（不创建、不修改文件）
- 不要执行任何命令
- 只输出分析结果和计划

**输出格式**：
先用简洁的语言描述你的理解，然后输出以下结构化计划：

```markdown
## 分析摘要
[1-2 句话描述任务的核心]

## 项目现状
[关键文件和结构，有哪些需要特别注意的]

## 执行计划
1. [第一步：做什么，改哪个文件，预期结果]
2. [第二步：...]
...

## 风险提示
[如有风险在这里标注，没有则写"无明显风险"]
```
"""


def cmd_plan(api: YukiAPI, model: str, task: str, cwd: str | None = None) -> bool:
    """
    Plan Mode：分析任务 → 生成计划 → 用户确认 → 执行或放弃。

    Returns True if user confirmed and handed off to agent,
    False if user cancelled or error occurred.
    """
    work_dir = os.path.abspath(cwd or os.getcwd())
    orig_cwd = os.getcwd()

    try:
        os.chdir(work_dir)
    except OSError:
        work_dir = orig_cwd

    console.print()
    console.print(Rule(f"[bold cyan][plan] 计划模式[/]  [cyan]{model}[/]"))

    # 发现上下文文件
    ctx_files = discover_context_files(work_dir)
    ctx_text = load_context_for_directory(work_dir)

    # 构建 plan 消息
    messages = [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
    ]
    if ctx_text:
        messages.append({"role": "system", "content": "# 项目上下文\n" + ctx_text})
    messages.append({"role": "user", "content": f"任务：{task}\n\n当前目录：{work_dir}"})

    console.print(f"[dim]上下文文件: {len(ctx_files)} 个[/]  [dim]工作目录: {work_dir}[/]\n")

    # 调用模型生成计划
    try:
        with console.status("[cyan]分析项目中…[/]", spinner="dots"):
            result = api.chat_once(model, messages, temperature=0.3)
    except Exception as e:
        console.print(f"[red]分析失败: {e}[/]")
        return False

    answer = result.content.strip()

    # 展示推理过程（如果有）
    if result.thinking.strip():
        console.print(Panel(
            Text(result.thinking.strip(), style="dim", overflow="fold"),
            title="[yellow][think] 推理过程[/]", title_align="left",
            border_style="yellow", box=box.ROUNDED, padding=(0, 2)))

    # 展示完整计划
    console.print(Panel(
        Text(answer, style="white", overflow="fold"),
        title="[bold cyan] 执行计划[/]", title_align="left",
        border_style="cyan", box=box.ROUNDED, padding=(1, 2)))

    # 询问用户确认
    console.print()
    try:
        choice = console.input(
            "[bold]确认执行？[/] "
            "[green][enter] 执行[/]  "
            "[yellow]q[yellow] 放弃[/]  "
            "[cyan]e[cyan] 仅编辑计划后执行[/]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "q"

    if choice in ("q", "quit", "exit"):
        console.print("[yellow]已放弃执行。[/]")
        return False

    # e = let user edit the plan then hand to agent
    # For now treat e the same as enter (hand to agent with plan as context)
    # A future enhancement would be to open plan in editor

    console.print(f"[green]开始执行计划…[/]\n")
    return True
