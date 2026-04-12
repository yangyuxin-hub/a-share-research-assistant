"""MainAgent 单元测试

直接回答类测试需要有效的 API Key（401 错误时跳过）。
标的分析类测试需要 Tushare Token（数据不可用时降级为 answered）。
"""

import pytest


class TestDirectAnswer:
    """直接回答类问题（不调用工具）"""

    def test_greeting(self, session_state, anthropic_client):
        from ashare_research_assistant.agents.main_agent import MainAgent

        agent = MainAgent(
            market_data_provider=_dummy_provider(),
            announcement_provider=_dummy_provider(),
            news_provider=_dummy_provider(),
            anthropic_client=anthropic_client,
            trace_store=_dummy_trace_store(),
        )
        state = session_state.model_copy(
            update={"user_input": "你好"}
        )
        result = agent.run(state)
        assert result.stage == "answered"
        assert result.direct_answer is not None
        assert len(result.direct_answer) > 0

    def test_knowledge_question(self, session_state, anthropic_client):
        from ashare_research_assistant.agents.main_agent import MainAgent

        agent = MainAgent(
            market_data_provider=_dummy_provider(),
            announcement_provider=_dummy_provider(),
            news_provider=_dummy_provider(),
            anthropic_client=anthropic_client,
            trace_store=_dummy_trace_store(),
        )
        state = session_state.model_copy(
            update={"user_input": "PE是什么意思"}
        )
        result = agent.run(state)
        assert result.stage == "answered"
        assert "PE" in result.direct_answer or "市盈" in result.direct_answer

    def test_identity_question(self, session_state, anthropic_client):
        from ashare_research_assistant.agents.main_agent import MainAgent

        agent = MainAgent(
            market_data_provider=_dummy_provider(),
            announcement_provider=_dummy_provider(),
            news_provider=_dummy_provider(),
            anthropic_client=anthropic_client,
            trace_store=_dummy_trace_store(),
        )
        state = session_state.model_copy(
            update={"user_input": "你是谁"}
        )
        result = agent.run(state)
        assert result.stage == "answered"
        assert result.direct_answer is not None


class TestResolveStock:
    """标的解析类问题"""

    def test_stock_code(self, session_state, anthropic_client):
        from ashare_research_assistant.agents.main_agent import MainAgent

        agent = MainAgent(
            market_data_provider=_dummy_provider(),
            announcement_provider=_dummy_provider(),
            news_provider=_dummy_provider(),
            anthropic_client=anthropic_client,
            trace_store=_dummy_trace_store(),
        )
        state = session_state.model_copy(
            update={"user_input": "600519"}
        )
        result = agent.run(state)
        # 两种合法结果：completed（完整分析）或 answered（价格快照）
        assert result.stage in ("completed", "answered", "degraded")
        if result.stage == "answered":
            assert result.direct_answer is not None


# ── 辅助函数 ──────────────────────────────────────────────────────────────


def _dummy_provider():
    """返回空实现的 provider，用于不依赖数据源的工具测试。"""
    from ashare_research_assistant.providers.base import (
        AnnouncementProvider,
        MarketDataProvider,
        NewsProvider,
    )
    from ashare_research_assistant.core.models import StockIdentifier

    class DummyMarketData(MarketDataProvider):
        def resolve_stock(self, query):
            if query == "600519":
                return [StockIdentifier(symbol="600519", name="贵州茅台")]
            return []

        def get_stock_profile(self, symbol):
            return None

        def get_price_snapshot(self, symbol):
            return None

        def get_daily_bars(self, symbol, start_date, end_date):
            return []

        def get_daily_factors(self, symbol, start_date, end_date):
            return []

    class DummyAnnouncement(AnnouncementProvider):
        def search_announcements(self, symbol, start_date, end_date, max_results=10):
            return []

    class DummyNews(NewsProvider):
        def search_company_news(self, symbol, start_date, end_date, max_results=10):
            return []

    return DummyMarketData()


def _dummy_trace_store():
    """返回空实现的 trace store。"""
    from ashare_research_assistant.services.trace_store import TraceStore

    class NoOpTraceStore(TraceStore):
        def __init__(self):
            pass  # 不写文件

        def append(self, event):
            pass

        def append_many(self, events):
            pass

        def read_by_turn(self, turn_id):
            return []

    return NoOpTraceStore()
