from types import SimpleNamespace


def test_main_agent_parses_textual_commit_opinion_tool_call(session_state):
    from ashare_research_assistant.agents.main_agent import MainAgent
    from ashare_research_assistant.core.models import StockIdentifier
    from ashare_research_assistant.providers.base import (
        AnnouncementProvider,
        MarketDataProvider,
        NewsProvider,
    )
    from ashare_research_assistant.services.trace_store import TraceStore

    class DummyMarket(MarketDataProvider):
        def resolve_stock(self, query):
            return [StockIdentifier(symbol="600519", name="贵州茅台", exchange="SSE")]

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

    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    stop_reason="tool_use",
                    usage=SimpleNamespace(input_tokens=100, output_tokens=20),
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="resolve-1",
                            name="resolve_stock",
                            input={"query": "贵州茅台"},
                        )
                    ],
                )
            return SimpleNamespace(
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=80, output_tokens=40),
                content=[
                    SimpleNamespace(
                        type="text",
                        text=(
                            "<tool_call>\n"
                            "<function=commit_opinion>\n"
                            "<parameter=stance>neutral</parameter>\n"
                            "<parameter=confidence>medium</parameter>\n"
                            "<parameter=one_liner>估值合理，关注动销</parameter>\n"
                            "<parameter=market_narrative>市场关注提价和增长放缓。</parameter>\n"
                            "<parameter=thesis>茅台长期护城河仍在，但短期增长放缓。</parameter>\n"
                            "<parameter=core_drivers>[\"品牌壁垒强\", \"提价支撑利润\"]</parameter>\n"
                            "<parameter=key_risks>[\"消费疲软\"]</parameter>\n"
                            "<parameter=debate_points>[\"估值是否充分反映增速放缓\"]</parameter>\n"
                            "<parameter=watch_points>[\"批价\", \"动销\"]</parameter>\n"
                            "<parameter=price_target_low>1200</parameter>\n"
                            "<parameter=price_target_high>1400</parameter>\n"
                            "<parameter=horizon_label>1m</parameter>\n"
                            "<parameter=anchor_summary>基于近期支撑位和估值。</parameter>\n"
                            "<parameter=evidence_chain>[]</parameter>\n"
                            "</function>\n"
                            "</tool_call>"
                        ),
                    )
                ],
            )

    agent = MainAgent(
        market_data_provider=DummyMarket(),
        announcement_provider=DummyAnnouncement(),
        news_provider=DummyNews(),
        anthropic_client=SimpleNamespace(messages=FakeMessages()),
        trace_store=NoOpTraceStore(),
        model="fake-model",
    )

    result = agent.run(session_state.model_copy(update={"user_input": "分析贵州茅台"}))

    assert result.stage == "completed"
    assert result.output_draft is not None
    assert result.output_draft.symbol == "600519"
    assert result.output_draft.one_liner == "估值合理，关注动销"
    assert result.direct_answer is None
    assert result.usage_stats is not None
    assert result.usage_stats.llm_calls == 2
    assert result.usage_stats.input_tokens == 180
    assert result.usage_stats.output_tokens == 60
    assert result.usage_stats.total_tokens == 240
    assert result.usage_stats.elapsed_ms >= 0
