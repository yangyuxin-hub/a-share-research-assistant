"""Intent Router Agent — Agentic Loop 版本。

工作流：
1. LLM 分析用户输入，判断大致意图
2. 遇到股票名称/代码时，主动调用 resolve_stock 获取真实数据
3. 基于查询结果决定是否需要追问
4. 调用 commit_intent 提交最终判断

这样"是否需要澄清"是基于真实数据得出的结论，而不是 LLM 直觉猜测。
"""

import json
import logging
import re
from typing import Callable, Optional

import anthropic

from ashare_research_assistant.core.models import RouterResult, StockIdentifier
from ashare_research_assistant.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)

MAX_LOOP_ITERATIONS = 6  # 防止无限循环

# ── 工具定义 ────────────────────────────────────────────────────────────────

_TOOL_RESOLVE_STOCK = {
    "name": "resolve_stock",
    "description": (
        "查询股票代码或名称，返回 A 股真实匹配列表。"
        "遇到任何股票名称/代码/简称时应先调用此工具，再决定意图和是否需要澄清。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": '股票代码（如 600519）或名称片段（如"平安"、"茅台"、"中国平安"）',
            }
        },
        "required": ["query"],
    },
}

_TOOL_COMMIT_INTENT = {
    "name": "commit_intent",
    "description": "在充分了解股票实体和用户意图后，提交最终路由结果。",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent_type": {
                "type": "string",
                "enum": [
                    "single_stock_analysis",
                    "stock_compare_or_followup",
                    "hot_candidate_discovery",
                    "theme_or_topic_exploration",
                    "general_market_question",
                    "knowledge_question",
                    "clarification_required",
                ],
                "description": "意图类型",
            },
            "resolved_symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "已通过 resolve_stock 确认的股票代码列表（如 ['600519', '000858']）",
            },
            "theme_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主题探索时的关键词列表",
            },
            "confidence": {
                "type": "number",
                "description": "意图识别置信度 0-1",
            },
            "clarification_needed": {
                "type": "boolean",
                "description": "是否需要向用户追问",
            },
            "clarification_reason": {
                "type": "string",
                "description": "需要追问的原因，clarification_needed=true 时必填",
            },
        },
        "required": ["intent_type", "resolved_symbols", "confidence", "clarification_needed"],
    },
}

_TOOLS = [_TOOL_RESOLVE_STOCK, _TOOL_COMMIT_INTENT]

# ── System Prompt ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是 A 股投研助手的意图路由模块。

## 工作流程
1. 分析用户输入，判断大致意图
2. 凡是涉及股票名称/代码/简称，必须先调用 resolve_stock 查询真实数据
3. 根据查询结果判断：是否有歧义？是否需要追问？
4. 调用 commit_intent 提交最终判断

## 速度规则
- 如果用户输入的是 6 位股票代码（如 600519），可以**同时调用 resolve_stock 和 commit_intent**，无需等待 resolve_stock 结果再决定意图。
- 明确的股票分析请求，直接在一次响应中同时发起两个工具调用。

## 意图类型
- single_stock_analysis：用户明确要分析某只股票（resolve_stock 后确认唯一）
- stock_compare_or_followup：比较多只股票，或在对话中追问
- hot_candidate_discovery：寻找热门/强势候选股
- theme_or_topic_exploration：探索板块/主题（AI、新能源、医药等）
- general_market_question：大盘行情等需要实时数据的市场问题
- knowledge_question：纯概念、知识、术语解释、问候、闲聊、询问助手身份能力，不需要实时数据，例如"PE是什么意思""你好""你能做什么""MACD金叉是什么"
- clarification_required：输入极度模糊，无法判断

## 何时 clarification_needed=true
- resolve_stock 返回多个候选，且用户意图是单票分析
- 多只股票的比较分析，但解析不到具体股票
- 输入极度模糊，连意图类型都无法确定

## 注意
- resolve_stock 返回空，不一定需要追问——可能是主题词而非股票名
- 主题探索可以不解析具体股票，直接提交 theme_keywords
- hot_candidate_discovery 不需要提取具体股票
"""


# ── Router Agent ─────────────────────────────────────────────────────────────

class RouterAgent:
    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        anthropic_client: anthropic.Anthropic,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self._provider = market_data_provider
        self._client = anthropic_client
        self._model = model

    def route(
        self,
        user_input: str,
        session_context: Optional[str] = None,
        progress_cb: Optional[Callable[[str, str], None]] = None,
    ) -> RouterResult:
        """Agentic Loop 主入口。

        LLM 可以多次调用 resolve_stock 探索，最终调用 commit_intent 提交结果。
        """
        # 初始消息
        if session_context:
            first_message = f"[会话背景]\n{session_context}\n\n[当前输入]\n{user_input}"
        else:
            first_message = user_input

        messages: list[dict] = [{"role": "user", "content": first_message}]

        # 本轮解析缓存：symbol -> StockIdentifier
        resolved_cache: dict[str, StockIdentifier] = {}

        for iteration in range(MAX_LOOP_ITERATIONS):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=_SYSTEM_PROMPT,
                    tools=_TOOLS,
                    tool_choice={"type": "any"},
                    messages=messages,
                )
            except Exception as e:
                logger.error(f"RouterAgent LLM 调用失败 (iteration={iteration}): {e}")
                return self._fallback_route(user_input)

            logger.debug(f"Router iteration={iteration}, stop_reason={response.stop_reason}")

            # LLM 不再调用工具，但也没有调用 commit_intent → 降级
            if response.stop_reason == "end_turn":
                logger.warning("LLM 未调用 commit_intent 就结束，尝试降级")
                return self._fallback_route(user_input)

            # 收集本轮所有 tool_use 块
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if not tool_use_blocks:
                return self._fallback_route(user_input)

            # 将 LLM 的回复加入消息历史
            messages.append({"role": "assistant", "content": response.content})

            # 处理每个工具调用，收集 tool_result
            tool_results = []
            commit_result: Optional[dict] = None

            for block in tool_use_blocks:
                if block.name == "resolve_stock":
                    query = block.input.get("query", "")
                    if progress_cb:
                        progress_cb("resolve_stock", query)
                    result_text = self._handle_resolve_stock(block.input, resolved_cache)
                    if progress_cb:
                        # 简短摘要：找到几只
                        try:
                            import json as _json
                            hits = _json.loads(result_text)
                            brief = "、".join(f"{h['name']}({h['symbol']})" for h in hits[:3]) if isinstance(hits, list) else result_text[:60]
                        except Exception:
                            brief = result_text[:60]
                        progress_cb("resolve_stock_result", brief)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

                elif block.name == "commit_intent":
                    # commit_intent 不需要返回内容，直接提取结果
                    commit_result = block.input
                    if progress_cb:
                        intent = commit_result.get("intent_type", "?")
                        conf = commit_result.get("confidence", 0)
                        symbols = commit_result.get("resolved_symbols", [])
                        sym_str = f" [{', '.join(symbols)}]" if symbols else ""
                        progress_cb("commit_intent", f"{intent}{sym_str}  置信 {conf:.0%}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "已提交",
                    })

            # 如果本轮有 commit_intent，构建最终结果
            if commit_result is not None:
                return self._build_result(commit_result, resolved_cache)

            # 否则把 tool_results 追加到消息，继续循环
            messages.append({"role": "user", "content": tool_results})

        logger.error(f"RouterAgent 超过最大迭代次数 {MAX_LOOP_ITERATIONS}，降级")
        return self._fallback_route(user_input)

    # ── 工具处理 ──────────────────────────────────────────────────────────────

    def _handle_resolve_stock(
        self,
        tool_input: dict,
        resolved_cache: dict[str, StockIdentifier],
    ) -> str:
        """执行 resolve_stock，更新缓存，返回格式化结果字符串。"""
        query = tool_input.get("query", "").strip()
        if not query:
            return "[]"

        candidates = self._provider.resolve_stock(query)
        if not candidates:
            return f'未找到与"{query}"匹配的股票'

        # 写入缓存
        for stock in candidates:
            resolved_cache[stock.symbol] = stock

        # 格式化给 LLM 看
        items = [
            {"symbol": s.symbol, "name": s.name, "exchange": s.exchange}
            for s in candidates
        ]
        return json.dumps(items, ensure_ascii=False)

    # ── 结果构建 ──────────────────────────────────────────────────────────────

    def _build_result(
        self,
        commit: dict,
        resolved_cache: dict[str, StockIdentifier],
    ) -> RouterResult:
        """将 commit_intent 的输出转换为 RouterResult。"""
        intent_type = commit.get("intent_type", "general_market_question")

        # 兜底规则：没有任何标的解析成功
        # 硬阻断意图（需要标的）：强制追问
        # 软兜底意图（不需要标的）：允许继续，降低置信度即可
        HARD_BLOCKED_INTENTS = {"single_stock_analysis", "stock_compare_or_followup"}
        if not resolved_cache:
            if intent_type in HARD_BLOCKED_INTENTS:
                return RouterResult(
                    intent_type="clarification_required",
                    resolved_entities=[],
                    confidence=0.0,
                    clarification_needed=True,
                    clarification_reason="无法识别股票名称，请提供具体的股票代码或全称",
                )
            # 主题探索 / 热股发现 / 市场问题：不需要标的，可继续
            return RouterResult(
                intent_type=intent_type,
                resolved_entities=[],
                confidence=0.3,
                clarification_needed=False,
            )

        resolved_symbols: list[str] = commit.get("resolved_symbols", [])
        theme_keywords: list[str] = commit.get("theme_keywords", [])
        confidence: float = float(commit.get("confidence", 0.5))
        clarification_needed: bool = bool(commit.get("clarification_needed", False))
        clarification_reason: Optional[str] = commit.get("clarification_reason")

        # 从缓存中取出完整的 StockIdentifier
        resolved_entities: list[StockIdentifier] = []
        for symbol in resolved_symbols:
            if symbol in resolved_cache:
                resolved_entities.append(resolved_cache[symbol])
            else:
                # LLM 提交了一个不在缓存中的 symbol（理论上不该发生）
                logger.warning(f"commit_intent 中的 symbol {symbol!r} 不在缓存，尝试补查")
                fallback = self._provider.resolve_stock(symbol)
                if fallback:
                    resolved_entities.append(fallback[0])

        return RouterResult(
            intent_type=intent_type,
            resolved_entities=resolved_entities,
            theme_keywords=theme_keywords,
            confidence=confidence,
            clarification_needed=clarification_needed,
            clarification_reason=clarification_reason,
        )

    # ── 降级规则 ──────────────────────────────────────────────────────────────

    def _fallback_route(self, user_input: str) -> RouterResult:
        """LLM 失败或超限时的规则降级：先匹配 6 位代码，再尝试 resolve_stock 全文搜索。"""
        # 1. 精确匹配 6 位 A 股代码
        code_pattern = re.compile(r"\b[036]\d{5}\b")
        codes = code_pattern.findall(user_input)
        resolved: list[StockIdentifier] = []
        seen: set[str] = set()

        if codes:
            for code in codes:
                for stock in self._provider.resolve_stock(code):
                    if stock.symbol not in seen:
                        seen.add(stock.symbol)
                        resolved.append(stock)

        # 2. 没有代码时，尝试把整段输入作为股票名称查询
        if not resolved:
            candidates = self._provider.resolve_stock(user_input.strip())
            if not candidates:
                # 提取 2-5 字中文词片段再试
                cn_words = re.findall(r'[\u4e00-\u9fff]{2,5}', user_input)
                for word in cn_words:
                    hits = self._provider.resolve_stock(word)
                    for s in hits:
                        if s.symbol not in seen:
                            seen.add(s.symbol)
                            candidates.append(s)
            for s in candidates:
                if s.symbol not in seen:
                    seen.add(s.symbol)
                    resolved.append(s)

        if resolved:
            return RouterResult(
                intent_type="single_stock_analysis",
                resolved_entities=resolved,
                confidence=0.6,
                clarification_needed=len(resolved) > 1,
                clarification_reason="找到多个候选标的，请确认分析哪一只" if len(resolved) > 1 else None,
            )

        return RouterResult(
            intent_type="general_market_question",
            resolved_entities=[],
            confidence=0.3,
            clarification_needed=False,
        )
