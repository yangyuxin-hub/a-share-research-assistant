def test_web_server_uses_configured_anthropic_model(monkeypatch):
    """Web server must not fall back to Orchestrator's default model."""
    from ashare_research_assistant.web import server

    captured: dict = {}

    class DummyAnthropic:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    class DummyProvider:
        def __init__(self, *args, **kwargs):
            pass

    class DummyTraceStore:
        def __init__(self, *args, **kwargs):
            pass

    class DummyOrchestrator:
        def __init__(self, **kwargs):
            captured["orchestrator_kwargs"] = kwargs

    monkeypatch.setattr(server, "_orchestrator", None)
    monkeypatch.setattr(server.settings, "anthropic_model", "custom-model")
    monkeypatch.setattr(server.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(server.settings, "anthropic_base_url", "")
    monkeypatch.setattr(server, "anthropic", type("AnthropicModule", (), {"Anthropic": DummyAnthropic}))
    monkeypatch.setattr(server, "TushareMarketDataProvider", DummyProvider)
    monkeypatch.setattr(server, "CninfoAnnouncementProvider", DummyProvider)
    monkeypatch.setattr(server, "AKShareNewsProvider", DummyProvider)
    monkeypatch.setattr(server, "WebSearchProvider", DummyProvider)
    monkeypatch.setattr(server, "AKShareHotlistProvider", DummyProvider)
    monkeypatch.setattr(server, "TraceStore", DummyTraceStore)
    monkeypatch.setattr(server, "Orchestrator", DummyOrchestrator)

    server._get_orchestrator()

    assert captured["orchestrator_kwargs"]["model"] == "custom-model"


def test_agent_defaults_use_configured_anthropic_model(monkeypatch):
    from ashare_research_assistant.agents import main_agent

    monkeypatch.setattr(main_agent.settings, "anthropic_model", "custom-model")

    class DummyProvider:
        pass

    class DummyTraceStore:
        pass

    agent = main_agent.MainAgent(
        market_data_provider=DummyProvider(),
        announcement_provider=DummyProvider(),
        news_provider=DummyProvider(),
        anthropic_client=object(),
        trace_store=DummyTraceStore(),
    )

    assert agent._model == "custom-model"


def test_legacy_llm_components_default_to_configured_model(monkeypatch):
    from ashare_research_assistant.agents import evaluator, stock_research, synthesis
    from ashare_research_assistant.services import price_target_engine

    monkeypatch.setattr(evaluator.settings, "anthropic_model", "custom-model")
    monkeypatch.setattr(stock_research.settings, "anthropic_model", "custom-model")
    monkeypatch.setattr(synthesis.settings, "anthropic_model", "custom-model")
    monkeypatch.setattr(price_target_engine.settings, "anthropic_model", "custom-model")

    assert evaluator.EvaluatorAgent(object())._model == "custom-model"
    assert price_target_engine.PriceTargetEngine(object())._model == "custom-model"
    assert synthesis.SynthesisAgent(object())._model == "custom-model"
    assert stock_research.StockResearchAgent(
        object(),
        price_target_engine.PriceTargetEngine(object()),
    )._model == "custom-model"
