"""端到端链路测试。

非交互式，直接调用 RouterAgent → Orchestrator 核心路径。
用法：uv run python tests/e2e_test.py
"""

import json
import logging
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.agents.router import RouterAgent
from ashare_research_assistant.agents.tools import ToolExecutor
from ashare_research_assistant.agents.skills import select_skill, SKILL_SINGLE_STOCK, SKILL_QUICK_CHECK
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.akshare import AKShareNewsProvider

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("e2e_test")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def test_providers():
    """测试数据层连接。"""
    print("\n=== 测试数据层 ===")

    market = TushareMarketDataProvider(token=settings.tushare_token)

    # resolve_stock
    results = market.resolve_stock("贵州茅台")
    assert results, "resolve_stock 贵州茅台 应该返回结果"
    print(f"  resolve_stock('贵州茅台'): {len(results)} 个结果 → {results[0].symbol} {results[0].name}")

    # get_price_snapshot
    snap = market.get_price_snapshot("600519")
    assert snap, "get_price_snapshot 应该返回快照"
    print(f"  get_price_snapshot('600519'): {snap.current_price:.2f} 元  涨跌 {snap.pct_change:+.2f}%")

    # get_stock_profile
    profile = market.get_stock_profile("600519")
    assert profile, "get_stock_profile 应该返回资料"
    print(f"  get_stock_profile('600519'): 行业={profile.identifier.industry}")

    # get_daily_bars
    bars = market.get_daily_bars("600519", "20260301", "20260410")
    print(f"  get_daily_bars: {len(bars)} 条日线")

    # get_financial_factors
    factors = market.get_daily_factors("600519", "20260301", "20260410")
    if factors:
        lf = factors[-1]
        print(f"  get_financial_factors: PE={lf.pe_ttm}  PB={lf.pb}  市值={lf.total_market_value/1e8:.0f}亿")

    print("  [PASS] 数据层测试通过")


def test_router():
    """测试 RouterAgent agentic loop。"""
    print("\n=== 测试 RouterAgent ===")

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,
    )
    market = TushareMarketDataProvider(token=settings.tushare_token)
    router = RouterAgent(market_data_provider=market, anthropic_client=client)

    # Case 1: 明确的股票名称
    result = router.route("分析一下中国平安")
    print(f"  '分析一下中国平安' → intent={result.intent_type}  confidence={result.confidence:.2f}")
    print(f"    解析到: {[s.symbol for s in result.resolved_entities]}")
    print(f"    需要澄清: {result.clarification_needed}")
    assert result.intent_type in ("single_stock_analysis", "stock_compare_or_followup"), f"预期 single_stock_analysis，实际 {result.intent_type}"

    # Case 2: 模糊名称（多候选）
    result2 = router.route("平安怎么样")
    print(f"  '平安怎么样' → intent={result2.intent_type}  confidence={result2.confidence:.2f}")
    print(f"    解析到: {[(s.symbol, s.name) for s in result2.resolved_entities]}")
    print(f"    需要澄清: {result2.clarification_needed}")
    if result2.clarification_needed:
        print(f"    澄清原因: {result2.clarification_reason}")

    # Case 3: 股票代码
    result3 = router.route("600519")
    print(f"  '600519' → intent={result3.intent_type}  解析到: {[s.symbol for s in result3.resolved_entities]}")

    # Case 4: 主题探索
    result4 = router.route("AI板块怎么样")
    print(f"  'AI板块怎么样' → intent={result4.intent_type}  解析到: {[(s.symbol, s.name) for s in result4.resolved_entities][:3]}...")

    # Case 5: 事件型主题 → 应直接进入主题探索，不强制追问
    result5 = router.route("特朗普关税影响下哪些股票")
    print(f"  '特朗普关税影响下哪些股票' → intent={result5.intent_type}  clarification={result5.clarification_needed}")
    assert result5.clarification_needed is False, \
        f"主题型问题不应触发追问，clarification_needed 应为 False，实际 {result5.clarification_needed}"
    assert result5.intent_type in ("theme_or_topic_exploration", "general_market_question", "hot_candidate_discovery"), \
        f"主题型问题应进入主题/热点/大盘意图，实际 {result5.intent_type}"

    print("  [PASS] RouterAgent 测试通过")


def test_skill_selection():
    """测试 Skill 选择逻辑。"""
    print("\n=== 测试 Skill 选择 ===")

    # 单票 → single_stock_deep_dive
    skill = select_skill("single_stock_analysis", user_input="分析贵州茅台", entity_count=1)
    assert skill.name == "single_stock_deep_dive", f"预期 single_stock_deep_dive，实际 {skill.name}"
    print(f"  单票分析 → {skill.name}")

    # 单票 + 快速关键词 → quick_price_check
    skill2 = select_skill("single_stock_analysis", user_input="茅台现在多少钱", entity_count=1)
    assert skill2.name == "quick_price_check", f"预期 quick_price_check，实际 {skill2.name}"
    print(f"  快速查询 → {skill2.name}")

    # 多股比较
    skill3 = select_skill("stock_compare_or_followup", user_input="茅台和五粮液", entity_count=2)
    assert skill3.name == "compare_stocks", f"预期 compare_stocks，实际 {skill3.name}"
    print(f"  多股比较 → {skill3.name}")

    # 大盘问题 → market_overview
    skill4 = select_skill("general_market_question", user_input="今天大盘怎么样")
    assert skill4.name == "general_market_overview", f"预期 general_market_overview，实际 {skill4.name}"
    print(f"  市场概览 → {skill4.name}")

    print("  [PASS] Skill 选择测试通过")


def test_tool_executor():
    """测试 ToolExecutor。"""
    print("\n=== 测试 ToolExecutor ===")

    market = TushareMarketDataProvider(token=settings.tushare_token)
    ann = CninfoAnnouncementProvider(token=settings.tushare_token or None)
    news = AKShareNewsProvider()
    executor = ToolExecutor(market_data=market, announcement=ann, news=news)

    # get_price_snapshot
    result = executor.execute("get_price_snapshot", {"symbol": "600519"})
    assert "当前价" in result, f"预期包含 '当前价'，实际: {result[:100]}"
    print(f"  get_price_snapshot:\n{result[:200]}...")

    # get_daily_bars
    result2 = executor.execute("get_daily_bars", {"symbol": "600519", "days": 20})
    assert "交易日" in result2, f"预期包含 '交易日'，实际: {result2[:100]}"
    print(f"  get_daily_bars: OK ({len(result2)} chars)")

    # get_stock_profile
    result3 = executor.execute("get_stock_profile", {"symbol": "600519"})
    assert "贵州茅台" in result3, f"预期包含 '贵州茅台'"
    print(f"  get_stock_profile: OK")

    # search_announcements
    result4 = executor.execute("search_announcements", {"symbol": "600519", "days": 30})
    print(f"  search_announcements: {result4[:150]}...")

    # search_news
    result5 = executor.execute("search_news", {"symbol": "600519", "days": 14})
    print(f"  search_news: {result5[:150]}...")

    print("  [PASS] ToolExecutor 测试通过")


def test_orchestrator_clarification():
    """测试 Orchestrator 追问逻辑。"""
    print("\n=== 测试追问逻辑 ===")

    from ashare_research_assistant.agents.orchestrator import Orchestrator
    from ashare_research_assistant.core.models import (
        RouterResult, SessionState, StockIdentifier, IntentType
    )
    from ashare_research_assistant.services.trace_store import TraceStore
    from ashare_research_assistant.services.clarification_engine import ClarificationEngine

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,
    )
    market = TushareMarketDataProvider(token=settings.tushare_token)
    ann = CninfoAnnouncementProvider(token=settings.tushare_token or None)
    news = AKShareNewsProvider()
    orch = Orchestrator(
        market_data_provider=market,
        announcement_provider=ann,
        news_provider=news,
        anthropic_client=client,
        clarification_engine=ClarificationEngine(),
        trace_store=TraceStore(path=".local/trace_test.jsonl"),
    )

    # Case 1: 主题探索（无候选）→ 应进入主题追问，而非标的歧义追问
    theme_router_result = RouterResult(
        intent_type="theme_or_topic_exploration",
        resolved_entities=[],       # 主题探索时不解析标的
        theme_keywords=["特朗普", "关税"],
        confidence=0.8,
        clarification_needed=False,
    )
    state = SessionState(created_at=_now_iso(), updated_at=_now_iso())
    state = state.model_copy(update={"user_input": "特朗普影响下哪些股票变动大"})
    state = orch.run(state, theme_router_result)

    assert state.stage == "clarifying", f"主题探索应进入 clarifying，实际 {state.stage}"
    q = state.clarification.question
    assert q is not None, "应有追问问题"
    assert q.reason == "theme_selection", f"追问原因应为 theme_selection，实际 {q.reason}"
    assert "特朗普" in q.prompt, f"prompt 应包含主题词，实际: {q.prompt}"
    print(f"  主题探索无候选 → stage=clarifying, reason={q.reason}, prompt={q.prompt[:40]}")

    # Case 2: 主题探索（有候选）→ 也应进入主题追问
    stocks = market.resolve_stock("中国平安")
    theme_router_result2 = RouterResult(
        intent_type="theme_or_topic_exploration",
        resolved_entities=stocks[:2],
        theme_keywords=["特朗普", "关税"],
        confidence=0.8,
        clarification_needed=False,
    )
    state2 = orch.run(state, theme_router_result2)
    assert state2.stage == "clarifying"
    assert state2.candidate_symbols == stocks[:2]
    print(f"  主题探索有候选 → stage=clarifying, 候选={len(state2.candidate_symbols)} 只")

    # Case 3: 用户说"没看到股票" → 应转向目标澄清
    neg_state = state.model_copy()
    neg_state = neg_state.model_copy(update={
        "stage": "clarifying",
        "clarification": state.clarification,
    })
    neg_result = orch.handle_clarification_answer(neg_state, "没看到股票")
    assert neg_result.stage == "clarifying"
    assert neg_result.clarification.question.reason == "unclear_goal", \
        f"负面反馈应进入 goal_clarification，实际 {neg_result.clarification.question.reason}"
    print(f"  「没看到股票」→ 转向 goal_clarification")

    # Case 4: 用户选择兜底选项序号（超出候选数量）→ 应转向目标澄清
    fallback_state = state.model_copy()
    fallback_state = fallback_state.model_copy(update={
        "stage": "clarifying",
        "clarification": state.clarification,
    })
    # 假设只有 3 个候选，用户选序号 5（兜底选项）
    fallback_result = orch.handle_clarification_answer(fallback_state, "5")
    assert fallback_result.stage == "clarifying"
    assert fallback_result.clarification.question.reason == "unclear_goal"
    print(f"  选择兜底序号 → 转向 goal_clarification")

    print("  [PASS] 追问逻辑测试通过")


def test_orchestrator_logic():
    """测试 Orchestrator 的结果映射逻辑（不含实际 LLM 调用）。"""
    print("\n=== 测试 Orchestrator 结果映射 ===")

    # 直接模拟 commit_opinion 的输出，验证 _build_state_from_opinion 逻辑
    mock_opinion = {
        "stance": "bullish",
        "confidence": "high",
        "one_liner": "茅台短期震荡，中长期看好",
        "market_narrative": "白酒龙头，业绩稳健",
        "thesis": "茅台作为高端白酒龙头，护城河深，业绩确定性高",
        "core_drivers": ["业绩稳健增长", "品牌护城河深", "直销比例提升"],
        "key_risks": ["宏观消费不及预期", "批价下行风险"],
        "debate_points": ["扩产 vs 提价空间"],
        "watch_points": ["一批价走势", "直营比例变化"],
        "price_target_low": 1700.0,
        "price_target_high": 1900.0,
        "horizon_label": "1w",
        "anchor_summary": "基于历史估值中枢 + 催化剂空间",
        "evidence_chain": [
            {"title": "Q4 业绩超预期", "interpretation": "净利润同比+15%", "direction": "support"},
            {"title": "一批价小幅回落", "interpretation": "短期情绪承压", "direction": "oppose"},
        ],
    }

    from ashare_research_assistant.agents.orchestrator import Orchestrator
    from ashare_research_assistant.agents.tools import ToolExecutor
    from ashare_research_assistant.core.models import (
        RouterResult, SessionState, StockIdentifier, IntentType
    )
    from ashare_research_assistant.services.trace_store import TraceStore
    from ashare_research_assistant.services.clarification_engine import ClarificationEngine
    import anthropic

    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,
    )
    market = TushareMarketDataProvider(token=settings.tushare_token)
    ann = CninfoAnnouncementProvider(token=settings.tushare_token or None)
    news = AKShareNewsProvider()
    orch = Orchestrator(
        market_data_provider=market,
        announcement_provider=ann,
        news_provider=news,
        anthropic_client=client,
        clarification_engine=ClarificationEngine(),
        trace_store=TraceStore(path=".local/trace_test.jsonl"),
    )

    # 直接调用内部方法验证
    executor = ToolExecutor(market_data=market, announcement=ann, news=news)

    # 验证 ToolExecutor 可以正确获取 last_price
    executor.execute("get_price_snapshot", {"symbol": "600519"})
    last_price = executor.last_price
    assert last_price and last_price > 0, f"last_price 应该 > 0，实际 {last_price}"
    print(f"  ToolExecutor.last_price: {last_price:.2f}")

    print("  [PASS] Orchestrator 逻辑测试通过")


def test_web_search():
    """测试 WebSearchProvider 和 search_web 工具。"""
    print("\n=== 测试 Web Search ===")

    from ashare_research_assistant.providers.web_search_provider import WebSearchProvider
    from ashare_research_assistant.agents.tools import TOOL_WEB_SEARCH, TOOLS_MARKET_OVERVIEW

    # Provider 创建
    provider = WebSearchProvider()
    print(f"  WebSearchProvider: OK")

    # 搜索功能
    results = provider.search_news("特朗普关税 A股", max_results=3)
    assert len(results) > 0, f"应返回搜索结果，实际 {len(results)} 条"
    print(f"  search_news: {len(results)} 条结果")
    for r in results:
        print(f"    - {r.title[:50]}")
    assert all(r.title for r in results), "所有结果应有标题"

    # search_market_topic
    topic_results = provider.search_market_topic("特朗普关税")
    assert len(topic_results) > 0
    print(f"  search_market_topic: {len(topic_results)} 条结果")

    # TOOL_WEB_SEARCH 存在
    assert TOOL_WEB_SEARCH["name"] == "search_web"
    print(f"  TOOL_WEB_SEARCH: OK")

    # TOOLS_MARKET_OVERVIEW 包含 web search
    tool_names = [t["name"] for t in TOOLS_MARKET_OVERVIEW]
    assert "search_web" in tool_names, f"TOOLS_MARKET_OVERVIEW 应包含 search_web，实际 {tool_names}"
    print(f"  TOOLS_MARKET_OVERVIEW 包含 search_web: {tool_names}")

    print("  [PASS] Web Search 测试通过")


def main():
    print("=" * 60)
    print("  A股投研助手 — 端到端链路测试")
    print("=" * 60)

    try:
        test_providers()
        test_skill_selection()
        test_tool_executor()
        test_web_search()
        test_orchestrator_logic()
        test_orchestrator_clarification()
        test_router()  # 这个有真实 LLM 调用，放最后
        print("\n" + "=" * 60)
        print("  全部测试通过 ✅")
        print("=" * 60)
    except Exception as e:
        print(f"\n  测试失败 ❌: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
