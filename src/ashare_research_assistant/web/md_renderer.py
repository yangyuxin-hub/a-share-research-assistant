"""把核心模型对象渲染为 Markdown 字符串，供 Gradio Web 界面使用。"""

from ashare_research_assistant.core.models import (
    ClarificationQuestion,
    OpinionCard,
    SessionState,
)

_STANCE_EMOJI = {"看多": "📈", "中性": "➡️", "看空": "📉"}
_CONF_LABEL = {"低": "🔵 低", "中": "🟡 中", "高": "🟢 高"}
_DIRECTION_ICON = {"support": "✅", "oppose": "❌", "mixed": "〰️"}
_RELIABILITY_LABEL = {
    "official": "官方",
    "licensed": "授权数据",
    "aggregated": "聚合",
    "scraped": "采集",
}
_TOOL_LABEL: dict[str, str] = {
    "resolve_stock":        "解析股票",
    "resolve_stock_result": "解析结果",
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


def _render_fact_source(source) -> str:
    title = source.title or "未命名来源"
    title_text = f"[{title}]({source.url})" if source.url else title
    source_name = source.source_name or "未知来源"
    if source.endpoint:
        source_name = f"{source_name} / {source.endpoint}"

    meta = [f"来源：{source_name}"]
    if source.data_timestamp:
        meta.append(f"数据日期：{source.data_timestamp}")
    if source.published_at:
        meta.append(f"发布时间：{source.published_at}")
    if source.reliability:
        meta.append(f"可靠性：{_RELIABILITY_LABEL.get(source.reliability, source.reliability)}")
    return f"- {title_text}（{'；'.join(meta)}）"


_DIM_OPEN = '<div style="opacity:0.55;font-size:0.82em;margin-top:1.2em;border-top:1px solid #e5e7eb;padding-top:0.6em">'
_DIM_CLOSE = '</div>'


def _render_fact_sources(sources, *, empty_notice: str | None = None) -> list[str]:
    if not sources:
        if not empty_notice:
            return []
        body = [f"<strong>事实审查依据</strong>", "", f"- {empty_notice}"]
    else:
        body = [f"<strong>事实审查依据</strong>", "", *[_render_fact_source(source) for source in sources]]
    return ["", _DIM_OPEN, *body, _DIM_CLOSE]


def _render_usage_stats(stats) -> list[str]:
    if not stats:
        return []
    elapsed = f"{stats.elapsed_ms / 1000:.2f}s"
    token_parts = [
        f"输入 {stats.input_tokens:,}",
        f"输出 {stats.output_tokens:,}",
        f"合计 {stats.total_tokens:,}",
    ]
    if getattr(stats, "cache_creation_input_tokens", 0):
        token_parts.append(f"缓存写入 {stats.cache_creation_input_tokens:,}")
    if getattr(stats, "cache_read_input_tokens", 0):
        token_parts.append(f"缓存读取 {stats.cache_read_input_tokens:,}")

    if stats.cost_is_configured and stats.estimated_cost is not None:
        currency_symbol = "$" if stats.cost_currency.upper() == "USD" else f"{stats.cost_currency} "
        cost_text = f"{currency_symbol}{stats.estimated_cost:.6f}"
    else:
        cost_text = "未配置单价"

    return [
        "",
        _DIM_OPEN,
        "<strong>耗时与成本</strong>",
        "",
        f"- 耗时：{elapsed}",
        f"- LLM 调用：{stats.llm_calls}",
        f"- Token：{'；'.join(token_parts)}",
        f"- 估算 Cost：{cost_text}",
        _DIM_CLOSE,
    ]


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


def render_text_answer(text: str, fact_sources=None) -> str:
    parts = [text] if text else []
    parts.extend(_render_fact_sources(
        fact_sources,
        empty_notice="未调用外部数据源；本回答基于通用投研知识或助手说明。",
    ))
    return "\n\n".join(parts)


def render_opinion_card(card: OpinionCard) -> str:
    stance_emoji = _STANCE_EMOJI.get(card.stance_label, "")
    conf_label = _CONF_LABEL.get(card.confidence_label, card.confidence_label)
    price_str = f"{card.current_price:.2f} 元" if card.current_price is not None else "暂无行情数据"

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

    fact_sources = getattr(card, "fact_sources", None)
    parts += _render_fact_sources(
        fact_sources,
        empty_notice="未采集到可审查的外部数据源，请谨慎参考。",
    )

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
            parts.append(render_text_answer(answer, getattr(state, "fact_sources", None)))

    elif stage == "degraded":
        parts.append(
            "⚠️ 当前意图暂不支持完整分析。\n\n"
            "请尝试输入具体的股票代码或名称，如 `600519` 或 `贵州茅台`。"
        )

    else:
        parts.append("*分析未能生成结论，请换种方式提问。*")

    parts.extend(_render_usage_stats(getattr(state, "usage_stats", None)))

    return "\n\n".join(p for p in parts if p)
