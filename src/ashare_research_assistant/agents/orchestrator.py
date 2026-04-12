"""Orchestrator — Agentic Loop 版本。

架构变化：
  旧版：Orchestrator 硬编码 fetch_price → collect_evidence → research → evaluate → synthesize
  新版：Orchestrator 选 Skill，启动 agentic loop，让 LLM 自己决定调用哪些工具、调用几次

LLM 调用一次多轮对话，通过工具探索数据，最终调用 commit_opinion 提交结论。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import anthropic

from ashare_research_assistant.core.models import (
    AnalysisWindow,
    AnchorBasis,
    ClarificationState,
    EvidenceChainItem,
    EvaluationResult,
    ExpandedOpinionCard,
    OpinionCard,
    PriceTarget,
    RouterResult,
    SessionState,
    StockIdentifier,
    StockResearchDraft,
    TraceEvent,
)
from ashare_research_assistant.agents.tools import ToolExecutor
from ashare_research_assistant.agents.skills import Skill, select_skill
from ashare_research_assistant.providers.base import (
    AnnouncementProvider,
    MarketDataProvider,
    NewsProvider,
)
from ashare_research_assistant.services.clarification_engine import ClarificationEngine
from ashare_research_assistant.services.trace_store import TraceStore

logger = logging.getLogger(__name__)

_STANCE_MAP = {"bullish": "看多", "neutral": "中性", "bearish": "看空"}
_CONF_MAP = {"high": "高", "medium": "中", "low": "低"}


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


class Orchestrator:
    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        announcement_provider: AnnouncementProvider,
        news_provider: NewsProvider,
        anthropic_client: anthropic.Anthropic,
        clarification_engine: ClarificationEngine,
        trace_store: TraceStore,
        model: str = "claude-sonnet-4-6",
        hotlist_provider: Optional[object] = None,
        web_search: Optional[object] = None,
    ) -> None:
        self._market = market_data_provider
        self._ann = announcement_provider
        self._news = news_provider
        self._client = anthropic_client
        self._clarification = clarification_engine
        self._trace_store = trace_store
        self._model = model
        self._hotlist = hotlist_provider
        self._web_search = web_search

    def run(self, state: SessionState, router_result: RouterResult) -> SessionState:
        """主入口：根据路由结果选 Skill，启动 agentic loop。"""
        state = state.model_copy(update={"stage": "routing"})
        state.trace.append(_trace(
            state, "router", "intent_identified",
            f"意图={router_result.intent_type}, 置信={router_result.confidence:.2f}",
        ))

        # Clarification Gate
        if router_result.clarification_needed:
            return self._enter_clarification(state, router_result)

        intent = router_result.intent_type
        entities = router_result.resolved_entities

        # ── 不需要工具、直接回答的场景 ──────────────────────────────────────────
        # 纯概念/知识问题，用 LLM 知识直接回答，不进 agentic loop
        if intent == "knowledge_question":
            return self._direct_answer(state, router_result)

        # 通用市场询问（无具体股票/主题），直接回答
        if intent == "general_market_question" and not entities and not router_result.theme_keywords:
            return self._direct_answer(state, router_result)

        # 主题探索 + 无候选标的 → 可以先搜索网络信息，无需强求股票
        if intent == "theme_or_topic_exploration" and not entities:
            # 降级为市场概览 Skill 搜索网络即可
            skill = select_skill("general_market_question", user_input=state.user_input)
            state = state.model_copy(update={"stage": "researching"})
            state.trace.append(_trace(state, "orchestrator", "skill_selected", skill.name))
            return self._run_agentic_loop(state, skill, [])

        # 主题探索 + 有候选 → 让用户选一只
        if intent == "theme_or_topic_exploration":
            theme = (
                router_result.theme_keywords[0]
                if router_result.theme_keywords
                else state.user_input
            )
            return self._enter_theme_clarification(state, entities, theme)

        # 需要标的但没有解析到
        if intent in ("single_stock_analysis", "stock_compare_or_followup") and not entities:
            return self._enter_clarification(state, router_result)

        # 选 Skill
        skill = select_skill(
            intent_type=intent,
            user_input=state.user_input,
            entity_count=len(entities),
        )

        state = state.model_copy(update={
            "active_symbol": entities[0] if entities else None,
            "candidate_symbols": entities,
            "stage": "researching",
        })
        state.trace.append(_trace(state, "orchestrator", "skill_selected", skill.name))

        return self._run_agentic_loop(state, skill, entities)

    def handle_clarification_answer(
        self, state: SessionState, answer_text: str
    ) -> SessionState:
        """处理用户对追问的回答，继续流程。"""
        resolved = self._clarification.resolve_answer(
            question=state.clarification.question,
            answer_text=answer_text,
            candidates=state.candidate_symbols,
        )
        now = _now_iso()
        state = state.model_copy(update={
            "clarification": state.clarification.model_copy(update={
                "status": "answered",
                "answer_text": answer_text,
                "answered_at": now,
            })
        })
        state.trace.append(_trace(state, "orchestrator", "clarification_answered",
                                  answer_text[:50]))

        # 检测用户是否表示"没有想要的"——转向目标澄清
        NEGATIVE_PATTERNS = (
            "没看到", "没有", "看不到", "不在", "不是", "不对",
            "换", "其他", "不行", "不要", "重新",
        )
        if resolved is None and any(p in answer_text for p in NEGATIVE_PATTERNS):
            new_question = self._clarification.build_goal_clarification(state.user_input)
            state = state.model_copy(update={
                "stage": "clarifying",
                "clarification": ClarificationState(
                    status="pending",
                    question=new_question,
                    asked_at=now,
                ),
            })
            return state

        if resolved:
            skill = select_skill("single_stock_analysis", user_input=state.user_input)
            state = state.model_copy(update={
                "active_symbol": resolved,
                "stage": "researching",
            })
            return self._run_agentic_loop(state, skill, [resolved])

        # 无法解析，再次追问
        new_question = self._clarification.build_symbol_disambiguation(state.candidate_symbols)
        state = state.model_copy(update={
            "stage": "clarifying",
            "clarification": ClarificationState(
                status="pending",
                question=new_question,
                asked_at=now,
            ),
        })
        return state

    # ── Agentic Loop ──────────────────────────────────────────────────────────

    def _run_agentic_loop(
        self,
        state: SessionState,
        skill: Skill,
        entities: list[StockIdentifier],
    ) -> SessionState:
        """核心循环：LLM 自主调用工具 → 最终 commit_opinion。"""
        executor = ToolExecutor(
            market_data=self._market,
            announcement=self._ann,
            news=self._news,
            hotlist=self._hotlist,
            web_search=self._web_search,
        )

        # 构建初始消息
        messages = [{"role": "user", "content": self._build_initial_message(state, entities)}]
        tools = skill.tools_with_commit

        for iteration in range(skill.max_iterations):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=skill.system_prompt,
                    tools=tools,
                    messages=messages,
                )
            except Exception as e:
                logger.error(f"Agentic loop LLM 调用失败 (iter={iteration}): {e}")
                return self._degraded(state, f"LLM 调用失败：{e}")

            logger.debug(f"[{skill.name}] iter={iteration} stop_reason={response.stop_reason}")

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # LLM 没有调用任何工具就结束
            if response.stop_reason == "end_turn" and not tool_use_blocks:
                logger.warning(f"[{skill.name}] LLM 未调用 commit_opinion 就结束")
                return self._degraded(state, "分析未完成")

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            opinion: Optional[dict] = None

            for block in tool_use_blocks:
                if block.name == "commit_opinion":
                    opinion = block.input
                    state.trace.append(_trace(
                        state, "llm", "commit_opinion",
                        f"stance={opinion.get('stance')} confidence={opinion.get('confidence')}",
                    ))
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
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

            if opinion is not None:
                return self._build_state_from_opinion(
                    state, opinion, entities, executor.last_price
                )

            messages.append({"role": "user", "content": tool_results})

        logger.error(f"[{skill.name}] 超过最大迭代次数 {skill.max_iterations}")
        return self._degraded(state, f"超过最大迭代次数 {skill.max_iterations}")

    # ── 结果构建 ──────────────────────────────────────────────────────────────

    def _build_state_from_opinion(
        self,
        state: SessionState,
        opinion: dict,
        entities: list[StockIdentifier],
        last_price: Optional[float],
    ) -> SessionState:
        """将 commit_opinion 的输出映射到 SessionState 的各字段。"""
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

        # PriceTarget
        price_target = PriceTarget(
            current_price=current_price,
            expected_price_low=float(pt_low),
            expected_price_high=float(pt_high),
            horizon=horizon,
            pricing_logic_summary=opinion.get("anchor_summary", ""),
            anchor_basis=AnchorBasis(
                method="llm_driven",
                description=opinion.get("anchor_summary", ""),
            ),
        )

        # StockResearchDraft（保留供 trace 使用）
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

        # EvaluationResult
        evaluation = EvaluationResult(
            confidence=confidence,
            evidence_coverage="partial",
            warnings=[],
            stance_consistency=True,
        )

        # OpinionCard
        card = OpinionCard(
            symbol=symbol_str,
            company_name=company_name,
            stance_label=_STANCE_MAP.get(stance, "中性"),
            confidence_label=_CONF_MAP.get(confidence, "低"),
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

        # ExpandedOpinionCard
        evidence_chain = [
            EvidenceChainItem(
                title=ec["title"],
                interpretation=ec["interpretation"],
                direction=ec["direction"],
            )
            for ec in opinion.get("evidence_chain", [])[:5]
        ]
        expanded = ExpandedOpinionCard(
            **card.model_dump(),
            debate_points=opinion.get("debate_points", []),
            evidence_chain=evidence_chain,
            information_changes=[],
            anchor_summary=opinion.get("anchor_summary", ""),
        )

        working_memory = state.working_memory.model_copy(
            update={"active_task": expanded.model_dump_json()}
        )

        state = state.model_copy(update={
            "research_draft": draft,
            "evaluation": evaluation,
            "output_draft": card,
            "working_memory": working_memory,
            "stage": "completed",
        })
        state.trace.append(_trace(state, "orchestrator", "completed",
                                  f"{card.stance_label} | {card.one_liner}"))
        self._trace_store.append_many(state.trace)
        return state

    def _enter_theme_clarification(
        self,
        state: SessionState,
        candidates: list[StockIdentifier],
        theme: str,
    ) -> SessionState:
        now = _now_iso()
        question = self._clarification.build_theme_exploration(candidates, theme)
        state = state.model_copy(update={
            "candidate_symbols": candidates,
            "stage": "clarifying",
            "clarification": ClarificationState(
                status="pending",
                question=question,
                asked_at=now,
            ),
        })
        state.trace.append(_trace(state, "orchestrator", "clarification_triggered",
                                  f"主题探索：{theme}，候选 {len(candidates)} 只"))
        return state

    # ── Clarification ─────────────────────────────────────────────────────────

    def _enter_clarification(
        self, state: SessionState, router_result: RouterResult
    ) -> SessionState:
        now = _now_iso()
        candidates = router_result.resolved_entities

        # 如果有主题词但意图不明确，视为主题探索澄清
        if router_result.theme_keywords and not candidates:
            theme = router_result.theme_keywords[0]
            return self._enter_theme_clarification(state, [], theme)

        if len(candidates) > 1:
            question = self._clarification.build_symbol_disambiguation(candidates)
        elif candidates:
            # 唯一候选，直接进分析
            skill = select_skill(router_result.intent_type, user_input=state.user_input)
            state = state.model_copy(update={
                "active_symbol": candidates[0],
                "candidate_symbols": candidates,
                "stage": "researching",
            })
            return self._run_agentic_loop(state, skill, candidates)
        else:
            question = self._clarification.build_goal_clarification(state.user_input)

        state = state.model_copy(update={
            "candidate_symbols": candidates,
            "stage": "clarifying",
            "clarification": ClarificationState(
                status="pending",
                question=question,
                asked_at=now,
            ),
        })
        state.trace.append(_trace(state, "orchestrator", "clarification_triggered",
                                  router_result.clarification_reason or "需要追问"))
        return state

    # ── 工具函数 ──────────────────────────────────────────────────────────────

    def _build_initial_message(
        self,
        state: SessionState,
        entities: list[StockIdentifier],
    ) -> str:
        lines = [f"用户问题：{state.user_input}"]
        if entities:
            stocks = "、".join(f"{e.name}（{e.symbol}）" for e in entities)
            lines.append(f"分析标的：{stocks}")
        lines.append("请开始分析，根据需要调用工具获取数据，完成后提交 commit_opinion。")
        return "\n".join(lines)

    def _degraded(self, state: SessionState, reason: str) -> SessionState:
        state = state.model_copy(update={"stage": "degraded"})
        state.trace.append(_trace(state, "orchestrator", "degraded", reason))
        self._trace_store.append_many(state.trace)
        return state

    # ── 直接回答（无工具） ──────────────────────────────────────────────────────

    def _direct_answer(self, state: SessionState, router_result: RouterResult) -> SessionState:
        """纯知识/概念问答，不调用任何工具，LLM 直接回答。"""
        answer_prompt = (
            "你是一个简洁的 A 股投研助手。用户问的是概念/知识问题，"
            "请用简洁准确的语言直接回答，不需要调用任何工具。\n\n"
            f"用户问题：{state.user_input}\n\n"
            "回答："
        )

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=(
                    "你是 A 股投研助手，擅长用简洁专业的语言解释金融概念和投研知识。\n"
                    "风格：准确、克制、有例子。不夸大，不废话。"
                ),
                messages=[{"role": "user", "content": answer_prompt}],
                # 注意：这里不传 tools 参数，LLM 只能说话，无法调用工具
            )
        except Exception as e:
            logger.error(f"_direct_answer LLM 调用失败: {e}")
            return self._degraded(state, f"回答生成失败：{e}")

        text = "".join(
            block.text for block in response.content
            if hasattr(block, "text")
        )

        state = state.model_copy(update={
            "stage": "answered",
            "direct_answer": text,
            "intent": router_result.intent_type,
            "intent_confidence": router_result.confidence,
        })
        state.trace.append(_trace(state, "orchestrator", "direct_answer",
                                  text[:60].replace("\n", " ")))
        self._trace_store.append_many(state.trace)
        return state

