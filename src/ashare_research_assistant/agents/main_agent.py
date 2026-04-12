"""Unified Main Agent — 意图路由 + 投研分析全部合一。

一次 LLM 调用，全部工具可见，模型自己判断：
- "你好" → 直接回话，不调工具
- "茅台怎么样" → 先 resolve_stock，再按需调行情/公告/新闻
- "PE是什么" → 直接回话
- "今天大盘怎么样" → search_web + get_hot_list

**关键约束**：涉及股票名称/代码时，必须先 resolve_stock，再决定下一步。
这个顺序在 system prompt 里硬约束，不在前置层强制。
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import anthropic
from anthropic.types import TextBlock

from ashare_research_assistant.core.models import (
    AnalysisWindow,
    AnchorBasis,
    ClarificationState,
    EvidenceChainItem,
    EvaluationResult,
    ExpandedOpinionCard,
    OpinionCard,
    PriceTarget,
    SessionState,
    StockIdentifier,
    StockResearchDraft,
    TraceEvent,
)
from ashare_research_assistant.agents.tools import (
    TOOL_GET_STOCK_PROFILE,
    TOOL_GET_PRICE_SNAPSHOT,
    TOOL_GET_DAILY_BARS,
    TOOL_GET_FINANCIAL_FACTORS,
    TOOL_SEARCH_ANNOUNCEMENTS,
    TOOL_SEARCH_NEWS,
    TOOL_GET_HOT_LIST,
    TOOL_WEB_SEARCH,
    ToolExecutor,
)
from ashare_research_assistant.providers.base import (
    AnnouncementProvider,
    MarketDataProvider,
    NewsProvider,
)
from ashare_research_assistant.services.trace_store import TraceStore

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12
_DIRECT_ANSWER_KEYWORDS = (
    "你好", "您好", "hi", "hello", "hey", "hi,",
    "你是谁", "你能做什么", "有什么用", "介绍一下", "怎么用",
    "pe是什么", "pb是什么", "eps是什么", "roe是什么", "是什么意思",
    "macd", "金叉", "死叉", "kdj", "boll", "术语",
    "涨跌停", "停牌", "st", "退市",
    "问候", "早安", "晚安", "你好呀",
)

# 这些词出现 → 快速查询（不是直接回答，但触发 resolve_stock → get_price_snapshot 路径）
_QUICK_QUERY_PATTERNS = (
    "多少钱", "现价", "今天价格", "现在价格", "当前价",
    "今天涨", "今天跌", "今日涨跌",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace(state: SessionState, actor: str, action: str, summary: str) -> TraceEvent:
    return TraceEvent(
        turn_id=state.turn_id,
        stage=state.stage,
        actor=actor,
        action=action,
        summary=summary,
        created_at=_now_iso(),
    )


# ── 工具定义 ──────────────────────────────────────────────────────────────────

TOOL_RESOLVE_STOCK = {
    "name": "resolve_stock",
    "description": (
        "查询股票代码或名称，返回 A 股真实匹配列表。"
        "凡涉及股票名称/代码/简称时，**必须先调用此工具**，拿到具体股票代码后，"
        "再决定是否调用行情/公告/新闻等数据工具。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": '股票代码（如 600519）或名称片段（如"茅台"、"平安"）',
            }
        },
        "required": ["query"],
    },
}

TOOL_COMMIT_OPINION = {
    "name": "commit_opinion",
    "description": (
        "数据收集和分析完成后，提交最终投研观点。"
        "调用此工具意味着分析结束，请确保已收集足够数据。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {
                "type": "string",
                "enum": ["bullish", "neutral", "bearish"],
                "description": "多空立场",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "置信度",
            },
            "one_liner": {
                "type": "string",
                "description": "一句话结论，20 字以内，结论优先",
            },
            "market_narrative": {
                "type": "string",
                "description": "市场当前对该股的主叙事，1-2 句",
            },
            "thesis": {
                "type": "string",
                "description": "核心投资逻辑，2-3 句",
            },
            "core_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "核心驱动因素，3-5 条，每条须有数据或事件支撑",
            },
            "key_risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主要风险，2-4 条",
            },
            "debate_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "多空分歧点，1-3 条",
            },
            "watch_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "后续观察点，1-3 条",
            },
            "price_target_low": {"type": "number", "description": "预期价格区间下沿"},
            "price_target_high": {"type": "number", "description": "预期价格区间上沿"},
            "horizon_label": {
                "type": "string",
                "enum": ["1-3d", "1w", "2w", "1m", "custom"],
                "description": "判断期限",
            },
            "anchor_summary": {"type": "string", "description": "价位锚定依据摘要，50 字以内"},
            "evidence_chain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "interpretation": {"type": "string"},
                        "direction": {"type": "string", "enum": ["support", "oppose", "mixed"]},
                    },
                    "required": ["title", "interpretation", "direction"],
                },
                "description": "关键证据链，最多 5 条",
            },
        },
        "required": ["stance", "confidence", "one_liner", "thesis", "core_drivers", "key_risks", "horizon_label"],
    },
}

TOOL_COMMIT_ANSWER = {
    "name": "commit_answer",
    "description": (
        "直接提交文字回答。适用场景："
        "纯概念/知识/术语/百科类问题，无需数据分析，例如："
        "'PE是什么意思'、'MACD金叉是什么'、'你好'。"
        "注意：涉及股票名称或代码的查询，无论表述如何，都应使用 commit_opinion 提交完整分析，"
        "不要用 commit_answer。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "直接回答用户的文字内容"},
        },
        "required": ["text"],
    },
}

TOOL_COMMIT_CLARIFICATION = {
    "name": "commit_clarification",
    "description": (
        "用户输入涉及股票但存在歧义（如名称模糊、多只候选）或意图极度模糊时，"
        "提交追问请求，模型不应自行猜测。clarification_type 不同，问法也不同。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "clarification_type": {
                "type": "string",
                "enum": ["symbol_disambiguation", "goal_clarification", "theme_exploration"],
                "description": (
                    "追问类型：symbol_disambiguation=多只候选让用户选一只；"
                    "goal_clarification=意图不明确，询问用户想做什么；"
                    "theme_exploration=探索主题但需要具体标的"
                ),
            },
            "candidates": {
                "type": "array",
                "description": "resolve_stock 返回的候选列表，格式：[{\"symbol\":\"\",\"name\":\"\"},...]",
            },
            "question": {"type": "string", "description": "追问的具体问题"},
        },
        "required": ["clarification_type", "question"],
    },
}

# ── 全部工具列表 ───────────────────────────────────────────────────────────────

ALL_TOOLS = [
    # 股票解析（第一步必须）
    TOOL_RESOLVE_STOCK,
    # 行情/财务数据（resolve_stock 后使用）
    TOOL_GET_STOCK_PROFILE,
    TOOL_GET_PRICE_SNAPSHOT,
    TOOL_GET_DAILY_BARS,
    TOOL_GET_FINANCIAL_FACTORS,
    TOOL_SEARCH_ANNOUNCEMENTS,
    TOOL_SEARCH_NEWS,
    # 市场概览（无需 resolve_stock）
    TOOL_GET_HOT_LIST,
    TOOL_WEB_SEARCH,
    # 提交
    TOOL_COMMIT_OPINION,
    TOOL_COMMIT_ANSWER,
    TOOL_COMMIT_CLARIFICATION,
]


# ── System Prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是 A 股投研助手，全程中文，风格简洁。

## 工具调用规则（必须遵守）

1. **涉及股票名称/代码** → 第一步调用 resolve_stock
2. **大盘/宏观/事件询问** → 直接调用 search_web 或 get_hot_list，无需 resolve_stock
3. **概念/术语/问候** → 调用 commit_answer（不要调用数据工具）
4. **多只候选或意图模糊** → 调用 commit_clarification
5. **数据收集完毕** → 调用 commit_opinion 提交完整分析

## 股票分析流程
resolve_stock 返回后，同时调用全部数据工具：get_stock_profile + get_price_snapshot + get_daily_bars + get_financial_factors + search_announcements + search_news。
数据返回后，调用 commit_opinion 提交结论。

## commit_opinion 必填
stance (bullish/neutral/bearish)、confidence (high/medium/low)、
one_liner（20字内）、thesis、core_drivers、key_risks、horizon_label。
数据缺失时注明，不虚构数据。

## commit_clarification
- symbol_disambiguation：多只候选
- goal_clarification：意图模糊
- candidates 字段放入候选列表，格式：[{"symbol":"600519","name":"贵州茅台"},...]
"""


# ── Main Agent ────────────────────────────────────────────────────────────────

class MainAgent:
    """统一 Agent：意图路由 + 数据收集 + 投研分析，一次 LLM 调用搞定。"""

    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        announcement_provider: AnnouncementProvider,
        news_provider: NewsProvider,
        anthropic_client: anthropic.Anthropic,
        trace_store: TraceStore,
        model: str = "claude-sonnet-4-6",
        hotlist_provider: Optional[object] = None,
        web_search: Optional[object] = None,
    ) -> None:
        self._market = market_data_provider
        self._ann = announcement_provider
        self._news = news_provider
        self._client = anthropic_client
        self._trace_store = trace_store
        self._model = model
        self._hotlist = hotlist_provider
        self._web_search = web_search
        self._executor: Optional[ToolExecutor] = None
        self._resolved_cache: dict[str, StockIdentifier] = {}

    def run(
        self,
        state: SessionState,
        progress_cb: Optional[Callable[[str, str], None]] = None,
    ) -> SessionState:
        """主入口：一次 agentic loop，返回填充后的 SessionState。"""
        user_input = state.user_input

        # 快速判断：是否直接回答（无工具）
        if self._is_direct_answer(user_input):
            return self._direct_answer(state, user_input)

        # Agentic Loop
        return self._agentic_loop(state, progress_cb=progress_cb)

    # ── Agentic Loop ───────────────────────────────────────────────────────────

    def _agentic_loop(
        self,
        state: SessionState,
        progress_cb: Optional[Callable[[str, str], None]] = None,
    ) -> SessionState:
        executor = ToolExecutor(
            market_data=self._market,
            announcement=self._ann,
            news=self._news,
            hotlist=self._hotlist,
            web_search=self._web_search,
        )
        self._executor = executor
        self._resolved_cache = {}

        user_input = state.user_input
        messages: list[dict] = [{"role": "user", "content": user_input}]

        for iteration in range(MAX_ITERATIONS):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=2048,
                    system=_SYSTEM_PROMPT,
                    tools=ALL_TOOLS,
                    tool_choice={"type": "any"},
                    messages=messages,
                )
            except Exception as e:
                logger.error(f"MainAgent LLM 调用失败 (iter={iteration}): {e}")
                return self._degraded(state, f"LLM 调用失败：{e}")

            logger.debug(f"[MainAgent] iter={iteration} stop_reason={response.stop_reason}")

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if not tool_use_blocks:
                # LLM 直接结束，无工具调用 → 降级
                logger.warning("LLM 无工具调用直接结束，降级")
                return self._degraded(state, "分析未完成")

            messages.append({"role": "assistant", "content": response.content})

            # 进度展示
            if progress_cb and tool_use_blocks:
                for b in tool_use_blocks:
                    if b.name not in ("commit_opinion", "commit_answer", "commit_clarification"):
                        args = b.input or {}
                        brief = (
                            args.get("symbol") or args.get("query") or
                            args.get("list_type") or str(args)[:40]
                        )
                        progress_cb(b.name, str(brief)[:60])

            tool_results = []
            final_type: Optional[str] = None
            final_data: Optional[dict] = None

            for block in tool_use_blocks:
                if block.name == "resolve_stock":
                    result_text = self._handle_resolve_stock(block.input)
                    if progress_cb:
                        try:
                            hits = json.loads(result_text)
                            brief = "、".join(
                                f"{h['name']}({h['symbol']})" for h in hits[:3]
                            ) if isinstance(hits, list) else result_text[:60]
                        except Exception:
                            brief = result_text[:60]
                        progress_cb("resolve_stock_result", brief)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

                elif block.name in ("commit_opinion", "commit_answer", "commit_clarification"):
                    final_type = block.name
                    final_data = block.input
                    if progress_cb:
                        progress_cb(block.name, "")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "已提交",
                    })

                else:
                    result_text = executor.execute(block.name, block.input)
                    state.trace.append(_trace(
                        state, "llm", f"tool:{block.name}",
                        result_text[:80].replace("\n", " "),
                    ))
                    if progress_cb and len(tool_use_blocks) == 1:
                        progress_cb(f"{block.name}_result", result_text[:80].replace("\n", " "))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

            messages.append({"role": "user", "content": tool_results})

            if final_type == "commit_answer":
                return self._build_direct_answer_state(state, final_data)

            if final_type == "commit_clarification":
                return self._build_clarification_state(state, final_data)

            if final_type == "commit_opinion":
                return self._build_opinion_state(
                    state, final_data, list(self._resolved_cache.values()), executor.last_price
                )

        # 超过迭代次数 → 尝试用已有数据构造回答
        resolved = list(self._resolved_cache.values())
        if resolved:
            stock = resolved[0]
            # 优先用已有的价格数据
            if executor.last_price is not None:
                answer_text = (
                    f"{stock.name}（{stock.symbol}）当前价格：{executor.last_price:.2f} 元。"
                )
                logger.warning(f"MainAgent 超过迭代次数，用已有价格数据构造回答")
                return self._build_direct_answer_state(state, {"text": answer_text})
            # 没有价格数据时，同步获取一个快照
            try:
                snap = self._market.get_price_snapshot(stock.symbol)
                if snap:
                    answer_text = (
                        f"{stock.name}（{stock.symbol}）当前价格：{snap.current_price:.2f} 元"
                        + (f"，涨跌：{snap.pct_change:+.2f}%" if snap.pct_change is not None else "")
                        + "。"
                    )
                    logger.warning(f"MainAgent 超过迭代次数，同步获取价格：{snap.current_price}")
                    return self._build_direct_answer_state(state, {"text": answer_text})
            except Exception as e:
                logger.warning(f"同步获取价格失败: {e}")

        # 市场/大盘查询超过迭代次数 → 直接获取热门榜兜底
        if not resolved and self._web_search:
            try:
                hot_result = self._web_search.search_news("A股大盘 今日行情", max_results=5)
                if hot_result:
                    lines = ["今日 A 股市场概况："]
                    for n in hot_result[:5]:
                        title = n.title[:60]
                        lines.append(f"• {title}")
                    answer_text = "\n".join(lines)
                    logger.warning("MainAgent 大盘查询超过迭代次数，用网络搜索结果兜底")
                    return self._build_direct_answer_state(state, {"text": answer_text})
            except Exception as e:
                logger.warning(f"大盘查询兜底失败: {e}")

        logger.error(f"MainAgent 超过最大迭代次数 {MAX_ITERATIONS}")
        return self._degraded(state, f"超过最大迭代次数 {MAX_ITERATIONS}")

        logger.error(f"MainAgent 超过最大迭代次数 {MAX_ITERATIONS}")
        return self._degraded(state, f"超过最大迭代次数 {MAX_ITERATIONS}")

    # ── 工具处理 ──────────────────────────────────────────────────────────────

    def _handle_resolve_stock(self, tool_input: dict) -> str:
        query = tool_input.get("query", "").strip()
        if not query:
            return "[]"

        candidates = self._market.resolve_stock(query)
        if not candidates:
            return f'未找到与"{query}"匹配的股票'

        for stock in candidates:
            self._resolved_cache[stock.symbol] = stock

        items = [
            {"symbol": s.symbol, "name": s.name, "exchange": s.exchange}
            for s in candidates
        ]
        return json.dumps(items, ensure_ascii=False)

    # ── 状态构建 ───────────────────────────────────────────────────────────────

    def _build_direct_answer_state(
        self, state: SessionState, data: dict
    ) -> SessionState:
        text = data.get("text", "")
        state = state.model_copy(update={
            "stage": "answered",
            "direct_answer": text,
            "intent": "knowledge_question",
            "intent_confidence": 1.0,
        })
        state.trace.append(_trace(state, "main_agent", "direct_answer",
                                  text[:60].replace("\n", " ")))
        self._trace_store.append_many(state.trace)
        return state

    def _build_clarification_state(
        self, state: SessionState, data: dict
    ) -> SessionState:
        clarification_type = data.get("clarification_type", "goal_clarification")
        question = data.get("question", "请确认您的具体需求")
        candidates = data.get("candidates") or []

        # 将 candidates JSON 字符串转回 list[StockIdentifier]
        resolved_candidates: list[StockIdentifier] = []
        if isinstance(candidates, list):
            for c in candidates:
                sym = c.get("symbol") or c.get("代码", "")
                name = c.get("name") or c.get("名称", "")
                if sym and sym in self._resolved_cache:
                    resolved_candidates.append(self._resolved_cache[sym])

        state = state.model_copy(update={
            "stage": "clarifying",
            "candidate_symbols": resolved_candidates,
            "clarification": ClarificationState(
                status="pending",
                question=question,
                asked_at=_now_iso(),
            ),
        })
        state.trace.append(_trace(state, "main_agent", "clarification_triggered",
                                  f"{clarification_type}: {question[:50]}"))
        self._trace_store.append_many(state.trace)
        return state

    def _build_opinion_state(
        self,
        state: SessionState,
        opinion: dict,
        entities: list[StockIdentifier],
        last_price: Optional[float],
    ) -> SessionState:
        now = _now_iso()
        symbol = entities[0] if entities else None
        symbol_str = symbol.symbol if symbol else "UNKNOWN"
        company_name = symbol.name if symbol else "未知"

        stance = opinion.get("stance", "neutral")
        confidence = opinion.get("confidence", "low")
        current_price = last_price or 0.0
        pt_low = opinion.get("price_target_low") or current_price
        pt_high = opinion.get("price_target_high") or current_price
        horizon = opinion.get("horizon_label", "1w")
        anchor_summary = opinion.get("anchor_summary", "")

        price_target = PriceTarget(
            current_price=current_price,
            expected_price_low=float(pt_low),
            expected_price_high=float(pt_high),
            target_label=f"{pt_low:.2f}–{pt_high:.2f}" if pt_low != pt_high else f"{current_price:.2f}",
            horizon=horizon,
            stance=stance,
            generated_at=now,
            pricing_logic_summary=anchor_summary,
            anchor_basis=[AnchorBasis(
                type="narrative_strength",
                description=anchor_summary or "基于当前市场叙事综合判断",
            )],
        )

        draft = StockResearchDraft(
            symbol=symbol_str,
            company_name=company_name,
            market_narrative=opinion.get("market_narrative", ""),
            thesis=opinion.get("thesis", ""),
            core_drivers=opinion.get("core_drivers", []),
            key_risks=opinion.get("key_risks", []),
            debate_points=opinion.get("debate_points", []),
            watch_points=opinion.get("watch_points", []),
            stance=stance,
            reasoning_window=AnalysisWindow(mode="auto", horizon_label=horizon),
            price_target=price_target,
        )

        evaluation = EvaluationResult(
            confidence=confidence,
            evidence_coverage="partial",
            conclusion_stability="moderate",
            warnings=[],
        )

        card = OpinionCard(
            symbol=symbol_str,
            company_name=company_name,
            stance_label={"bullish": "看多", "neutral": "中性", "bearish": "看空"}.get(stance, "中性"),
            confidence_label={"high": "高", "medium": "中", "low": "低"}.get(confidence, "低"),
            one_liner=opinion.get("one_liner", ""),
            current_price=current_price,
            expected_price_text=(
                f"目标区间 {pt_low:.2f}–{pt_high:.2f} 元（{horizon}）"
                if pt_low != pt_high else f"参考价 {current_price:.2f} 元"
            ),
            horizon_text=horizon,
            market_narrative=opinion.get("market_narrative", ""),
            core_drivers=opinion.get("core_drivers", []),
            key_risks=opinion.get("key_risks", []),
            watch_points=opinion.get("watch_points", []),
            generated_at=now,
        )

        evidence_chain = [
            EvidenceChainItem(
                title=ec.get("title", ""),
                interpretation=ec.get("interpretation", ""),
                direction=ec.get("direction", "mixed"),
            )
            for ec in opinion.get("evidence_chain", [])[:5]
            if isinstance(ec, dict)
        ]
        expanded = ExpandedOpinionCard(
            **card.model_dump(),
            debate_points=opinion.get("debate_points", []),
            evidence_chain=evidence_chain,
            information_changes=[],
            anchor_summary=anchor_summary,
        )

        working_memory = state.working_memory.model_copy(
            update={"active_task": expanded.model_dump_json()}
        )

        state = state.model_copy(update={
            "active_symbol": symbol,
            "candidate_symbols": entities,
            "intent": "single_stock_analysis",
            "intent_confidence": 0.8,
            "research_draft": draft,
            "evaluation": evaluation,
            "output_draft": card,
            "working_memory": working_memory,
            "stage": "completed",
        })
        state.trace.append(_trace(state, "main_agent", "completed",
                                  f"{card.stance_label} | {card.one_liner}"))
        self._trace_store.append_many(state.trace)
        return state

    # ── 直接回答 ───────────────────────────────────────────────────────────────

    def _direct_answer(self, state: SessionState, user_input: str) -> SessionState:
        """纯知识/闲聊/概念解释，不调用任何数据工具。"""
        system_text = (
            "You are A股投研助手, a professional Chinese A-share market research assistant. "
            "Your name is A股投研助手. You are NOT Claude, NOT made by Anthropic, "
            "and you have no other identity or persona. "
            "Always respond in Chinese (中文). "
            "Be concise and professional. "
            "If greeting: introduce yourself as A股投研助手 and briefly describe your capabilities "
            "(stock analysis, sector exploration, market overview, investment knowledge). "
            "If asking about terminology/concepts: explain in plain, accessible Chinese."
        )
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=[TextBlock(type="text", text=system_text)],
                messages=[{"role": "user", "content": user_input}],
            )
        except Exception as e:
            logger.error(f"_direct_answer LLM 调用失败: {e}")
            return self._degraded(state, f"回答生成失败：{e}")

        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return self._build_direct_answer_state(state, {"text": text})

    def _is_direct_answer(self, user_input: str) -> bool:
        """判断是否无需工具、直接回答。"""
        text = user_input.strip().lower()
        for kw in _DIRECT_ANSWER_KEYWORDS:
            if kw in text:
                return True
        # 问号结尾 + 明显是概念类问题
        if user_input.strip().endswith("？") or user_input.strip().endswith("?"):
            text_content = user_input.strip()[:-1].lower()
            concept_words = ("是什么", "什么意思", "如何", "怎样", "哪个", "哪些")
            if any(w in text_content for w in concept_words):
                # 排除明显是股票名的问题
                if not self._contains_stock_mention(user_input):
                    return True
        return False

    def _contains_stock_mention(self, text: str) -> bool:
        """简单启发式：包含 6 位数字或 2-5 字中文词（可能是股票名）。"""
        if re.search(r"\b[036]\d{5}\b", text):
            return True
        # 常见投研词汇（不是股票名）
        non_stock = {"pe", "pb", "eps", "roe", "毛利率", "净利率", "营收", "利润",
                     "资产负债", "现金流", "股价", "涨跌", "大盘", "指数", "板块",
                     "北向", "主力", "庄家", "筹码", "均线", "macd", "kdj", "boll"}
        text_lower = text.lower()
        for w in non_stock:
            if w in text_lower:
                return False
        return bool(re.search(r"[\u4e00-\u9fff]{2,5}", text))

    # ── 降级 ──────────────────────────────────────────────────────────────────

    def _degraded(self, state: SessionState, reason: str) -> SessionState:
        state = state.model_copy(update={"stage": "degraded"})
        state.trace.append(_trace(state, "main_agent", "degraded", reason))
        self._trace_store.append_many(state.trace)
        return state
