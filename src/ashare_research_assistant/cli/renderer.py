"""Rich CLI 渲染模块。

负责：观点卡、追问、状态提示的终端美化输出。
"""

import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from ashare_research_assistant.core.models import (
    ClarificationQuestion,
    ExpandedOpinionCard,
    OpinionCard,
    SessionState,
)

# Windows 下强制 UTF-8 输出
console = Console(highlight=False, emoji=False)

_STANCE_COLOR = {
    "看多": "bold green",
    "中性": "bold yellow",
    "看空": "bold red",
}
_CONF_COLOR = {
    "低": "dim",
    "中": "yellow",
    "高": "green",
}


def print_status(message: str) -> None:
    console.print(f"[dim]... {message}[/dim]")


def print_error(message: str) -> None:
    console.print(f"[bold red][!] {message}[/bold red]")


def print_opinion_card(card: OpinionCard) -> None:
    stance_style = _STANCE_COLOR.get(card.stance_label, "bold")
    conf_style = _CONF_COLOR.get(card.confidence_label, "")

    title = Text()
    title.append(f" {card.company_name}（{card.symbol}）  ")
    title.append(card.stance_label, style=stance_style)
    title.append("  置信：")
    title.append(card.confidence_label, style=conf_style)

    # 核心信息表格
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
    table.add_column(style="dim", width=10)
    table.add_column()

    table.add_row("判断", f"[bold]{card.one_liner}[/bold]")
    table.add_row("当前价", f"{card.current_price:.2f} 元")
    table.add_row("预期价位", card.expected_price_text)
    table.add_row("判断期限", card.horizon_text)
    table.add_row("", "")
    table.add_row("市场叙事", card.market_narrative)

    if card.core_drivers:
        table.add_row("核心驱动", "\n".join(f"• {d}" for d in card.core_drivers))
    if card.key_risks:
        table.add_row("主要风险", "\n".join(f"• {r}" for r in card.key_risks))
    if card.watch_points:
        table.add_row("观察点", "\n".join(f"• {w}" for w in card.watch_points))

    console.print()
    console.print(Panel(table, title=title, border_style="blue", padding=(0, 1)))
    console.print(
        f"[dim]  生成时间：{card.generated_at[:19]}  |  输入「展开」查看完整分析[/dim]"
    )
    console.print()


def print_expanded_card(card: ExpandedOpinionCard) -> None:
    print_opinion_card(card)

    if card.debate_points:
        console.print("[bold cyan]── 多空分歧 ──[/bold cyan]")
        for dp in card.debate_points:
            console.print(f"  [cyan]△[/cyan] {dp}")
        console.print()

    if card.evidence_chain:
        console.print("[bold cyan]── 证据链 ──[/bold cyan]")
        direction_icon = {"support": "[green]+[/green]", "oppose": "[red]-[/red]", "mixed": "[yellow]~[/yellow]"}
        for ec in card.evidence_chain:
            icon = direction_icon.get(ec.direction, "·")
            console.print(f"  {icon} {ec.title}")
            console.print(f"    [dim]{ec.interpretation}[/dim]")
        console.print()

    if card.anchor_summary:
        console.print(f"[bold cyan]── 价位锚定 ──[/bold cyan]")
        console.print(f"  {card.anchor_summary}")
        console.print()


def print_clarification(question: ClarificationQuestion) -> None:
    console.print()
    console.print(Panel(
        f"[bold]{question.prompt}[/bold]" +
        (f"\n[dim]{question.help_text}[/dim]" if question.help_text else ""),
        title="[yellow]需要确认[/yellow]",
        border_style="yellow",
        padding=(0, 1),
    ))

    if question.options:
        for i, opt in enumerate(question.options, 1):
            mark = " [green](推荐)[/green]" if opt.id == question.recommended_option_id else ""
            console.print(f"  [bold]{i}.[/bold] {opt.label}{mark}")
            console.print(f"     [dim]{opt.description}[/dim]")
    if question.allow_free_text:
        console.print("  [dim]（也可直接输入您的回答）[/dim]")
    console.print()


def print_degraded(state: SessionState) -> None:
    console.print(Panel(
        f"[yellow]当前意图暂不支持完整分析。\n"
        f"请尝试输入具体的股票代码或名称，如：600519 或 贵州茅台[/yellow]",
        title="[yellow]功能受限[/yellow]",
        border_style="yellow",
    ))


def print_welcome() -> None:
    console.print()
    console.print(Panel(
        "[bold]A 股投研助手[/bold]\n\n"
        "输入股票代码（如 [cyan]600519[/cyan]）、股票名称（如 [cyan]贵州茅台[/cyan]），\n"
        "或自然语言请求，开始分析。\n\n"
        "[dim]特殊命令：展开 | 帮助 | 退出[/dim]",
        border_style="blue",
        padding=(1, 2),
    ))
    console.print()
