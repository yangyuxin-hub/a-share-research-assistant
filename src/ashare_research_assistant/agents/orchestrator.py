"""Orchestrator — 简化版，委托给 MainAgent。

职责：
  - 初始化 MainAgent（合并了意图路由 + agentic loop）
  - 管理 SessionState 生命周期
  - 处理 clarification 追问与回答流程
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from ashare_research_assistant.agents.main_agent import MainAgent
from ashare_research_assistant.core.models import ClarificationState, RouterResult, SessionState
from ashare_research_assistant.providers.base import (
    AnnouncementProvider,
    MarketDataProvider,
    NewsProvider,
)
from ashare_research_assistant.services.clarification_engine import ClarificationEngine
from ashare_research_assistant.services.trace_store import TraceStore

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self._clarification = clarification_engine
        self._agent = MainAgent(
            market_data_provider=market_data_provider,
            announcement_provider=announcement_provider,
            news_provider=news_provider,
            anthropic_client=anthropic_client,
            trace_store=trace_store,
            model=model,
            hotlist_provider=hotlist_provider,
            web_search=web_search,
        )

    def run(
        self,
        state: SessionState,
        router_result: Optional[RouterResult] = None,
        progress_cb: Optional[Callable[[str, str], None]] = None,
    ) -> SessionState:
        """主入口：委托给 MainAgent 处理。

        router_result 参数保留接口兼容，但不再用于路由决策——MainAgent 自己判断。
        """
        state = state.model_copy(update={"stage": "running"})
        return self._agent.run(state, progress_cb=progress_cb)

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

        # 检测用户是否表示"没有想要的"——转向目标澄清
        NEGATIVE_PATTERNS = (
            "没看到", "没有", "看不到", "不在", "不是", "不对",
            "换", "其他", "不行", "不要", "重新",
        )
        if resolved is None and any(p in answer_text for p in NEGATIVE_PATTERNS):
            new_question = self._clarification.build_goal_clarification(state.user_input)
            return state.model_copy(update={
                "stage": "clarifying",
                "clarification": ClarificationState(
                    status="pending",
                    question=new_question,
                    asked_at=now,
                ),
            })

        if resolved:
            state = state.model_copy(update={
                "active_symbol": resolved,
                "candidate_symbols": [resolved],
                "stage": "running",
            })
            return self._agent.run(state)

        # 无法解析，再次追问
        new_question = self._clarification.build_symbol_disambiguation(state.candidate_symbols)
        return state.model_copy(update={
            "stage": "clarifying",
            "clarification": ClarificationState(
                status="pending",
                question=new_question,
                asked_at=now,
            ),
        })

    def degraded(self, state: SessionState, reason: str) -> SessionState:
        return state.model_copy(update={"stage": "degraded"})
