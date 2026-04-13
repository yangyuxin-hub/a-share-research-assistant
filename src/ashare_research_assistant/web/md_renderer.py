"""把核心模型对象渲染为 Markdown 字符串，供 Gradio Web 界面使用。"""

from ashare_research_assistant.core.models import (
    ClarificationQuestion,
    OpinionCard,
    SessionState,
)

_STANCE_EMOJI = {"看多": "📈", "中性": "➡️", "看空": "📉"}
_CONF_LABEL = {"低": "🔵 低", "中": "🟡 中", "高": "🟢 高"}
_DIRECTION_ICON = {"support": "✅", "oppose": "❌", "mixed": "〰️"}
_TOOL_LABEL: dict[str, str] = {
    "resolve_stock":        "解析股票",
    "commit_intent":        "确认意图",
    "get_stock_profile":    "基本面",
    "get_price_snapshot":   "价格快照",
    "get_daily_bars":       "历史 K 线",
    "get_financial_factors": "财务因子",
    "search_announcements": "公告搜索",
    "search_news":          "新闻搜索",
    "search_web":           "网络搜索",
    "get_hot_list":         "热门榜单",
    "commit_opinion":       "提交结论",
}


def render_tool_calls(tool_calls: list[tuple[str, str]]) -> str:
    """把 progress_cb 收集到的工具调用渲染为折叠块。"""
    if not tool_calls:
        return ""
    lines = ["<details><summary>📊 分析过程</summary>\n"]
    for name, brief in tool_calls:
        label = _TOOL_LABEL.get(name, name)
        suffix = f" — {brief}" if brief else ""
        lines.append(f"- **{label}**{suffix}")
    lines.append("\n</details>\n")
    return "\n".join(lines)


def render_opinion_card(card: OpinionCard) -> str:
    stance_emoji = _STANCE_EMOJI.get(card.stance_label, "")
    conf_label = _CONF_LABEL.get(card.confidence_label, card.confidence_label)
    price_str = f"{card.current_price:.2f} 元" if card.current_price is not None else "暂无"

    parts = [
        f"## {stance_emoji} {card.company_name}（{card.symbol}）",
        "",
        f"| 项目 | 内容 |",
        f"|------|------|",
        f"| **判断** | {card.one_liner} |",
        f"| **立场** | {card.stance_label} |",
        f"| **置信度** | {conf_label} |",
        f"| **当前价** | {price_str} |",
        f"| **预期价位** | {card.expected_price_text} |",
        f"| **判断期限** | {card.horizon_text} |",
        "",
        f"### 市场叙事",
        card.market_narrative or "—",
    ]

    if card.core_drivers:
        parts += ["", "### 核心驱动"]
        parts += [f"- {d}" for d in card.core_drivers]

    if card.key_risks:
        parts += ["", "### 主要风险"]
        parts += [f"- {r}" for r in card.key_risks]

    if card.watch_points:
        parts += ["", "### 观察点"]
        parts += [f"- {w}" for w in card.watch_points]

    # 证据链（来自 ExpandedOpinionCard，兼容基类）
    evidence = getattr(card, "evidence_chain", None)
    if evidence:
        parts += ["", "### 证据链"]
        for ec in evidence:
            icon = _DIRECTION_ICON.get(ec.direction, "·")
            parts.append(f"{icon} **{ec.title}** — {ec.interpretation}")

    # 价位锚定
    anchor = getattr(card, "anchor_summary", None)
    if anchor:
        parts += ["", f"### 价位锚定", anchor]

    # 多空分歧
    debate = getattr(card, "debate_points", None)
    if debate:
        parts += ["", "### 多空分歧"]
        parts += [f"- {d}" for d in debate]

    parts += ["", f"*生成时间：{card.generated_at[:19]}*"]
    parts += ["", "> 💡 输入 **展开** 查看完整分析"]

    return "\n".join(parts)


def render_clarification(question: ClarificationQuestion) -> str:
    parts = [f"### ❓ {question.prompt}"]
    if question.help_text:
        parts.append(f"*{question.help_text}*")
    if question.options:
        parts.append("")
        for i, opt in enumerate(question.options, 1):
            rec = " （推荐）" if opt.id == question.recommended_option_id else ""
            parts.append(f"**{i}.** {opt.label}{rec}")
            if opt.description:
                parts.append(f"   > {opt.description}")
    if question.allow_free_text:
        parts.append("")
        parts.append("*也可直接输入您的回答。*")
    return "\n".join(parts)


def render_state(state: SessionState, tool_calls: list[tuple[str, str]] | None = None) -> str:
    """把 SessionState 渲染为完整 Markdown 回复。"""
    parts: list[str] = []

    if tool_calls:
        parts.append(render_tool_calls(tool_calls))

    stage = state.stage

    if stage == "clarifying":
        question = state.clarification.question
        if question:
            parts.append(render_clarification(question))

    elif stage == "completed":
        card = state.output_draft
        if card:
            parts.append(render_opinion_card(card))

    elif stage == "answered":
        answer = state.direct_answer or ""
        if answer:
            parts.append(answer)

    elif stage == "degraded":
        parts.append(
            "⚠️ 当前意图暂不支持完整分析。\n\n"
            "请尝试输入具体的股票代码或名称，如 `600519` 或 `贵州茅台`。"
        )

    else:
        parts.append("*分析未能生成结论，请换种方式提问。*")

    return "\n\n".join(p for p in parts if p)
