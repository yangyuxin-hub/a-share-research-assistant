"""Provider 层测试"""

import pytest


class TestAKShareHotlistProvider:
    """AKShare 热门榜单 Provider"""

    def test_get_hot_stocks(self):
        pytest.importorskip("akshare")
        from ashare_research_assistant.providers.akshare.hotlist_provider import (
            AKShareHotlistProvider,
        )

        provider = AKShareHotlistProvider()
        # 网络可能超时，使用 skipif 装饰更合适
        try:
            items = provider.get_hot_stocks(top_n=5)
        except Exception:
            pytest.skip("网络不可达，跳过实际 API 调用")

        assert isinstance(items, list)
        if items:
            item = items[0]
            assert hasattr(item, "symbol")
            assert hasattr(item, "name")
            assert hasattr(item, "heat_score")

    def test_get_limit_up_pool(self):
        pytest.importorskip("akshare")
        from ashare_research_assistant.providers.akshare.hotlist_provider import (
            AKShareHotlistProvider,
        )

        provider = AKShareHotlistProvider()
        try:
            items = provider.get_limit_up_pool(date="20260413")
        except Exception:
            pytest.skip("网络不可达，跳过实际 API 调用")

        assert isinstance(items, list)


class TestWebSearchProvider:
    """网络搜索 Provider"""

    def test_search_news(self):
        pytest.importorskip("akshare")
        from ashare_research_assistant.providers.web_search_provider import (
            WebSearchProvider,
        )

        provider = WebSearchProvider()
        try:
            results = provider.search_news("A股大盘今日行情", max_results=3)
        except Exception:
            pytest.skip("网络不可达，跳过实际 API 调用")

        assert isinstance(results, list)


class TestClarificationEngine:
    """Clarification Engine 单元测试（无需网络）"""

    def test_build_symbol_disambiguation(self):
        from ashare_research_assistant.core.models import StockIdentifier
        from ashare_research_assistant.services.clarification_engine import (
            ClarificationEngine,
        )

        engine = ClarificationEngine()
        candidates = [
            StockIdentifier(symbol="600519", name="贵州茅台"),
            StockIdentifier(symbol="000858", name="五粮液"),
        ]
        question = engine.build_symbol_disambiguation(candidates)
        assert question.prompt
        assert len(question.options) == 3  # 2个候选 + 1个兜底

    def test_resolve_answer_by_index(self):
        from ashare_research_assistant.core.models import StockIdentifier
        from ashare_research_assistant.services.clarification_engine import (
            ClarificationEngine,
        )

        engine = ClarificationEngine()
        candidates = [
            StockIdentifier(symbol="600519", name="贵州茅台"),
            StockIdentifier(symbol="000858", name="五粮液"),
        ]
        question = engine.build_symbol_disambiguation(candidates)
        result = engine.resolve_answer(question, "1", candidates)
        assert result is not None
        assert result.symbol == "600519"

    def test_resolve_answer_by_name(self):
        from ashare_research_assistant.core.models import StockIdentifier
        from ashare_research_assistant.services.clarification_engine import (
            ClarificationEngine,
        )

        engine = ClarificationEngine()
        candidates = [
            StockIdentifier(symbol="600519", name="贵州茅台"),
            StockIdentifier(symbol="000858", name="五粮液"),
        ]
        question = engine.build_symbol_disambiguation(candidates)
        result = engine.resolve_answer(question, "贵州茅台", candidates)
        assert result is not None
        assert result.symbol == "600519"

    def test_build_goal_clarification(self):
        from ashare_research_assistant.services.clarification_engine import (
            ClarificationEngine,
        )

        engine = ClarificationEngine()
        question = engine.build_goal_clarification("看看这个")
        assert question.prompt
        assert len(question.options) >= 2
