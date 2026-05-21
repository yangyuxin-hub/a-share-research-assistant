from types import SimpleNamespace


def _agent():
    from ashare_research_assistant.agents.main_agent import MainAgent
    from ashare_research_assistant.providers.base import (
        AnnouncementProvider,
        MarketDataProvider,
        NewsProvider,
    )
    from ashare_research_assistant.services.trace_store import TraceStore

    class DummyMarket(MarketDataProvider):
        def resolve_stock(self, query):
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
        def search_announcements(self, symbol, start_date, end_date, keywords=None, max_results=10):
            return []

        def get_announcement_detail(self, announcement_id):
            return None

    class DummyNews(NewsProvider):
        def search_news(self, query, start_date, end_date, max_results=20):
            return []

        def search_company_news(self, symbol, start_date, end_date, max_results=10):
            return []

    class NoOpTraceStore(TraceStore):
        def __init__(self):
            pass

        def append_many(self, events):
            pass

    return MainAgent(
        market_data_provider=DummyMarket(),
        announcement_provider=DummyAnnouncement(),
        news_provider=DummyNews(),
        anthropic_client=SimpleNamespace(messages=SimpleNamespace()),
        trace_store=NoOpTraceStore(),
        model="fake-model",
    )


def test_opinion_state_normalizes_string_lists_and_missing_price(session_state):
    from ashare_research_assistant.core.models import StockIdentifier

    result = _agent()._build_opinion_state(
        session_state,
        {
            "stance": "neutral",
            "confidence": "low",
            "one_liner": "增长放缓，等待改善",
            "market_narrative": "",
            "thesis": "一季报增速放缓，渠道改革仍需观察。",
            "core_drivers": '["一季报增速放缓", "渠道改革推进"]',
            "key_risks": '["消费疲软"]',
            "debate_points": '["提价能否带动收入"]',
            "watch_points": '["批价", "动销"]',
            "horizon_label": "1m",
            "evidence_chain": '[{"title":"一季报","interpretation":"增速放缓","direction":"mixed"}]',
        },
        [StockIdentifier(symbol="600519", name="贵州茅台", exchange="SSE")],
        last_price=None,
    )

    assert result.stage == "completed"
    assert result.output_draft is not None
    assert result.output_draft.current_price is None
    assert result.output_draft.expected_price_text == "暂无行情数据"
    assert result.output_draft.market_narrative == "一季报增速放缓，渠道改革仍需观察。"
    assert result.output_draft.core_drivers == ["一季报增速放缓", "渠道改革推进"]
    assert result.output_draft.key_risks == ["消费疲软"]


def test_render_opinion_card_displays_missing_price_as_unavailable(session_state):
    from ashare_research_assistant.core.models import OpinionCard
    from ashare_research_assistant.web.md_renderer import render_opinion_card

    rendered = render_opinion_card(
        OpinionCard(
            symbol="600519",
            company_name="贵州茅台",
            stance_label="中性",
            confidence_label="低",
            one_liner="增长放缓，等待改善",
            current_price=None,
            expected_price_text="暂无行情数据",
            horizon_text="1m",
            market_narrative="一季报增速放缓，渠道改革仍需观察。",
            generated_at=session_state.created_at,
        )
    )

    assert "0.00 元" not in rendered
    assert "| **当前价** | 暂无行情数据 |" in rendered
    assert "| **预期价位** | 暂无行情数据 |" in rendered


def test_render_opinion_card_displays_fact_check_sources(session_state):
    from ashare_research_assistant.core.models import ExpandedOpinionCard, FactSourceItem
    from ashare_research_assistant.web.md_renderer import render_opinion_card

    rendered = render_opinion_card(
        ExpandedOpinionCard(
            symbol="600519",
            company_name="贵州茅台",
            stance_label="中性",
            confidence_label="低",
            one_liner="增长放缓，等待改善",
            current_price=1311.0,
            expected_price_text="目标区间 1250.00-1400.00 元（1m）",
            horizon_text="1m",
            market_narrative="一季报增速放缓，渠道改革仍需观察。",
            generated_at=session_state.created_at,
            fact_sources=[
                FactSourceItem(
                    kind="price",
                    title="价格快照：600519",
                    source_name="Tushare",
                    endpoint="daily",
                    reliability="licensed",
                    data_timestamp="20260521",
                    fetched_at="2026-05-21T08:00:00+00:00",
                ),
                FactSourceItem(
                    kind="news",
                    title="贵州茅台一季度净利润增长放缓",
                    source_name="东方财富",
                    endpoint="stock_news_em",
                    reliability="aggregated",
                    published_at="2026-05-20",
                    url="https://example.com/news",
                ),
            ],
        )
    )

    assert "### 事实审查依据" in rendered
    assert "价格快照：600519" in rendered
    assert "Tushare / daily" in rendered
    assert "数据日期：20260521" in rendered
    assert "[贵州茅台一季度净利润增长放缓](https://example.com/news)" in rendered


def test_tool_executor_collects_fact_sources_from_price_snapshot():
    from ashare_research_assistant.agents.tools import ToolExecutor
    from ashare_research_assistant.core.models import PriceSnapshot, SourceMeta
    from ashare_research_assistant.providers.base import (
        AnnouncementProvider,
        MarketDataProvider,
        NewsProvider,
    )

    class Market(MarketDataProvider):
        def resolve_stock(self, query):
            return []

        def get_stock_profile(self, symbol):
            return None

        def get_price_snapshot(self, symbol):
            return PriceSnapshot(
                symbol=symbol,
                trade_date="20260521",
                current_price=1311.0,
                data_timestamp="20260521",
                source=SourceMeta(
                    provider="Tushare",
                    endpoint="daily",
                    fetched_at="2026-05-21T08:00:00+00:00",
                    data_timestamp="20260521",
                    reliability="licensed",
                ),
            )

        def get_daily_bars(self, symbol, start_date, end_date):
            return []

        def get_daily_factors(self, symbol, start_date, end_date):
            return []

    class Announcement(AnnouncementProvider):
        def search_announcements(self, symbol, start_date, end_date, keywords=None, max_results=10):
            return []

        def get_announcement_detail(self, announcement_id):
            return None

    class News(NewsProvider):
        def search_news(self, query, start_date, end_date, max_results=20):
            return []

        def search_company_news(self, symbol, start_date, end_date, max_results=10):
            return []

    executor = ToolExecutor(Market(), Announcement(), News())
    executor.execute("get_price_snapshot", {"symbol": "600519"})

    assert executor.fact_sources
    source = executor.fact_sources[0]
    assert source["kind"] == "price"
    assert source["source_name"] == "Tushare"
    assert source["endpoint"] == "daily"
    assert source["data_timestamp"] == "20260521"


def test_tool_executor_collects_fact_sources_from_announcements_and_news():
    from ashare_research_assistant.agents.tools import ToolExecutor
    from ashare_research_assistant.core.models import AnnouncementItem, NewsItem, SourceMeta
    from ashare_research_assistant.providers.base import (
        AnnouncementProvider,
        MarketDataProvider,
        NewsProvider,
    )

    class Market(MarketDataProvider):
        def resolve_stock(self, query):
            return []

        def get_stock_profile(self, symbol):
            return None

        def get_price_snapshot(self, symbol):
            return None

        def get_daily_bars(self, symbol, start_date, end_date):
            return []

        def get_daily_factors(self, symbol, start_date, end_date):
            return []

    class Announcement(AnnouncementProvider):
        def search_announcements(self, symbol, start_date, end_date, keywords=None, max_results=10):
            return [
                AnnouncementItem(
                    id="ann-1",
                    symbol=symbol,
                    title="贵州茅台2026年第一季度报告",
                    publish_time="2026-04-25",
                    url="https://example.com/ann.pdf",
                    source=SourceMeta(
                        provider="cninfo_via_tushare",
                        endpoint="anns",
                        fetched_at="2026-05-21T08:00:00+00:00",
                        reliability="official",
                    ),
                )
            ]

        def get_announcement_detail(self, announcement_id):
            return None

    class News(NewsProvider):
        def search_news(self, query, start_date, end_date, max_results=20):
            return []

        def search_company_news(self, symbol, start_date, end_date, max_results=10):
            return [
                NewsItem(
                    id="news-1",
                    title="贵州茅台一季度净利润增长放缓",
                    publish_time="2026-05-20",
                    outlet="东方财富",
                    url="https://example.com/news",
                    related_symbols=[symbol],
                    source=SourceMeta(
                        provider="akshare",
                        endpoint="stock_news_em",
                        fetched_at="2026-05-21T08:00:00+00:00",
                        reliability="scraped",
                    ),
                )
            ]

    executor = ToolExecutor(Market(), Announcement(), News())
    executor.execute("search_announcements", {"symbol": "600519"})
    executor.execute("search_news", {"symbol": "600519"})

    kinds = {source["kind"] for source in executor.fact_sources}
    assert kinds == {"announcement", "news"}
    assert executor.fact_sources[0]["url"] == "https://example.com/ann.pdf"
    assert executor.fact_sources[1]["published_at"] == "2026-05-20"


def test_render_answered_state_displays_fact_check_sources(session_state):
    from ashare_research_assistant.core.models import FactSourceItem
    from ashare_research_assistant.web.md_renderer import render_state

    state = session_state.model_copy(update={
        "stage": "answered",
        "direct_answer": "AI 板块短期受算力链新闻催化，但分化加大。",
        "fact_sources": [
            FactSourceItem(
                kind="web",
                title="AI算力板块最新动态",
                source_name="SearchProvider",
                endpoint="news",
                reliability="aggregated",
                published_at="2026-05-21",
                url="https://example.com/ai-news",
            )
        ],
    })

    rendered = render_state(state)

    assert "AI 板块短期受算力链新闻催化" in rendered
    assert "### 事实审查依据" in rendered
    assert "[AI算力板块最新动态](https://example.com/ai-news)" in rendered


def test_direct_answer_state_preserves_fact_sources(session_state):
    result = _agent()._build_direct_answer_state(
        session_state,
        {"text": "今天大盘震荡，需结合实时资讯观察。"},
        fact_sources=[
            {
                "kind": "web",
                "title": "今日A股市场实时资讯",
                "source_name": "SearchProvider",
                "endpoint": "news",
                "reliability": "aggregated",
                "published_at": "2026-05-21",
                "url": "https://example.com/market",
            }
        ],
    )

    assert result.stage == "answered"
    assert result.fact_sources[0].title == "今日A股市场实时资讯"


def test_render_answered_state_displays_no_external_source_notice(session_state):
    from ashare_research_assistant.web.md_renderer import render_state

    state = session_state.model_copy(update={
        "stage": "answered",
        "direct_answer": "PE 是市盈率，用来衡量股价相对盈利的估值水平。",
    })

    rendered = render_state(state)

    assert "### 事实审查依据" in rendered
    assert "未调用外部数据源" in rendered


def test_render_text_answer_displays_fact_check_notice():
    from ashare_research_assistant.web.md_renderer import render_text_answer

    rendered = render_text_answer("使用说明：输入股票代码开始分析。")

    assert "使用说明：输入股票代码开始分析。" in rendered
    assert "### 事实审查依据" in rendered
    assert "未调用外部数据源" in rendered


def test_render_state_displays_usage_stats(session_state):
    from ashare_research_assistant.core.models import UsageStats
    from ashare_research_assistant.web.md_renderer import render_state

    state = session_state.model_copy(update={
        "stage": "answered",
        "direct_answer": "PE 是市盈率。",
        "usage_stats": UsageStats(
            elapsed_ms=1530,
            llm_calls=2,
            input_tokens=1000,
            output_tokens=250,
            total_tokens=1250,
            estimated_cost=0.0025,
            cost_currency="USD",
            cost_is_configured=True,
        ),
    })

    rendered = render_state(state)

    assert "### 耗时与成本" in rendered
    assert "1.53s" in rendered
    assert "2" in rendered
    assert "1,250" in rendered
    assert "$0.002500" in rendered
