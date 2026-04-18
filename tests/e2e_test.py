"""端到端链路测试。

非交互式，直接测试核心组件（Provider、ToolExecutor、Orchestrator、Skill）。
不再依赖已废弃的 RouterAgent 独立路由层。

用法：uv run python tests/e2e_test.py
"""

import logging
import sys
import io
from datetime import datetime, timezone

sys.path.insert(0, "src")

# Windows 控制台 UTF-8 兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.agents.tools import ToolExecutor
from ashare_research_assistant.agents.skills import select_skill, SKILL_SINGLE_STOCK, SKILL_QUICK_CHECK
from ashare_research_assistant.agents.orchestrator import Orchestrator
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.akshare import AKShareNewsProvider

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

    # 无匹配意图 → 兜底 market_overview
    skill5 = select_skill("knowledge_question", user_input="什么是PE")
    assert skill5.name == "general_market_overview", f"预期兜底 market_overview，实际 {skill5.name}"
    print(f"  兜底路由 → {skill5.name}")

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

    # last_price 跟踪
    assert executor.last_price is not None and executor.last_price > 0, \
        f"last_price 应被跟踪，实际: {executor.last_price}"
    print(f"  last_price 跟踪: {executor.last_price:.2f}")

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


def test_orchestrator_logic():
    """测试 Orchestrator 追问逻辑（ClarificationEngine + handle_clarification_answer）。"""
    print("\n=== 测试 Orchestrator 追问逻辑 ===")

    from ashare_research_assistant.core.models import StockIdentifier
    from ashare_research_assistant.services.clarification_engine import ClarificationEngine
    from ashare_research_assistant.services.trace_store import TraceStore

    clarification_engine = ClarificationEngine()
    trace_store = TraceStore(path=".local/trace_test.jsonl")

    # Case 1: ClarificationEngine.build_symbol_disambiguation
    candidates = [
        StockIdentifier(symbol="600519", name="贵州茅台"),
        StockIdentifier(symbol="000858", name="五粮液"),
    ]
    q = clarification_engine.build_symbol_disambiguation(candidates)
    assert q.prompt, "应有追问 prompt"
    assert len(q.options) == 3, f"应有 2 候选 + 1 兜底，实际 {len(q.options)}"
    print(f"  标的歧义追问: {q.prompt}，选项数={len(q.options)}")

    # Case 2: ClarificationEngine.build_goal_clarification
    goal_q = clarification_engine.build_goal_clarification("看看这个")
    assert goal_q.prompt, "应有目标澄清 prompt"
    assert goal_q.reason == "unclear_goal"
    assert len(goal_q.options) >= 2, f"目标澄清至少有 2 个选项，实际 {len(goal_q.options)}"
    print(f"  目标澄清: reason={goal_q.reason}，选项数={len(goal_q.options)}")

    # Case 3: ClarificationEngine.resolve_answer — 按序号
    resolved = clarification_engine.resolve_answer(q, "1", candidates)
    assert resolved is not None and resolved.symbol == "600519", \
        f"序号 1 应解析到 600519，实际 {resolved}"
    print(f"  按序号解析 '1' → {resolved.symbol} {resolved.name}")

    # Case 4: ClarificationEngine.resolve_answer — 按名称
    resolved2 = clarification_engine.resolve_answer(q, "五粮液", candidates)
    assert resolved2 is not None and resolved2.symbol == "000858", \
        f"'五粮液' 应解析到 000858"
    print(f"  按名称解析 '五粮液' → {resolved2.symbol} {resolved2.name}")

    # Case 5: ClarificationEngine.resolve_answer — 兜底序号（超出候选范围）→ None
    resolved3 = clarification_engine.resolve_answer(q, "3", candidates)
    assert resolved3 is None, "序号 3（兜底选项）应返回 None"
    print(f"  兜底序号 '3' → None（正确，应触发目标澄清）")

    # Case 6: Orchestrator.handle_clarification_answer — 负面反馈 → 目标澄清
    # test_orchestrator_logic 只测 ClarificationEngine 逻辑和 handle_clarification_answer 路径，
    # 该路径不触发 LLM 调用（resolve_answer 返回 None 时直接用 ClarificationEngine，不再调 agent）。
    # 不需要真实 API key。
    class _DummyAnthropic:
        pass

    market = TushareMarketDataProvider(token=settings.tushare_token)
    ann = CninfoAnnouncementProvider(token=settings.tushare_token or None)
    news = AKShareNewsProvider()
    orch = Orchestrator(
        market_data_provider=market,
        announcement_provider=ann,
        news_provider=news,
        anthropic_client=_DummyAnthropic(),
        clarification_engine=clarification_engine,
        trace_store=trace_store,
    )

    # 构造处于 clarifying 阶段的 SessionState
    from ashare_research_assistant.core.models import ClarificationState, SessionState

    state = SessionState(created_at=_now_iso(), updated_at=_now_iso())
    state = state.model_copy(update={
        "stage": "clarifying",
        "user_input": "平安怎么样",
        "candidate_symbols": candidates,
        "clarification": ClarificationState(
            status="pending",
            question=q,
            asked_at=_now_iso(),
        ),
    })

    # 用户说"没看到" → 应转向目标澄清
    result_state = orch.handle_clarification_answer(state, "没看到股票")
    assert result_state.stage == "clarifying", \
        f"负面反馈应停留在 clarifying，实际 {result_state.stage}"
    assert result_state.clarification.question.reason == "unclear_goal", \
        f"应转向 goal_clarification，实际 reason={result_state.clarification.question.reason}"
    print(f"  负面反馈 → stage={result_state.stage}, reason={result_state.clarification.question.reason}")

    # Case 7: Orchestrator.handle_clarification_answer — 选兜底选项（超出范围数字）
    # 数字超出候选范围但不包含负面关键词 → 留在标的歧义追问（让用户重新选）
    state2 = state.model_copy()
    result_state2 = orch.handle_clarification_answer(state2, "3")
    assert result_state2.stage == "clarifying"
    assert result_state2.clarification.question.reason == "ambiguous_symbol", \
        f"超出范围的数字应留在 ambiguous_symbol，实际 reason={result_state2.clarification.question.reason}"
    print(f"  选择兜底序号 '3' → ambiguous_symbol（留在标的追问，重新选择）")

    # Case 8: Orchestrator.handle_clarification_answer — 负面关键词 → 目标澄清
    state3 = state.model_copy()
    result_state3 = orch.handle_clarification_answer(state3, "都不对，换一个")
    assert result_state3.stage == "clarifying"
    assert result_state3.clarification.question.reason == "unclear_goal", \
        f"负面关键词应转向 goal_clarification，实际 reason={result_state3.clarification.question.reason}"
    print(f"  负面关键词 → goal_clarification（正确）")

    print("  [PASS] Orchestrator 追问逻辑测试通过")


def test_web_search():
    """测试 WebSearchProvider 和 search_web 工具。"""
    print("\n=== 测试 Web Search ===")

    from ashare_research_assistant.providers.web_search_provider import WebSearchProvider
    from ashare_research_assistant.agents.tools import TOOL_WEB_SEARCH, TOOLS_MARKET_OVERVIEW

    # Provider 创建
    provider = WebSearchProvider()
    print(f"  WebSearchProvider: OK")

    # 搜索功能（网络不可用时跳过）
    try:
        results = provider.search_news("A股大盘今日行情", max_results=3)
    except Exception as e:
        print(f"  search_news 跳过（网络不可达）: {e}")
    else:
        if len(results) == 0:
            print(f"  search_news 跳过（无结果，可能被风控）")
        else:
            print(f"  search_news: {len(results)} 条结果")
            for r in results:
                print(f"    - {r.title[:50]}")
            assert all(r.title for r in results), "所有结果应有标题"

    # search_market_topic
    try:
        topic_results = provider.search_news("AI板块行情")
    except Exception as e:
        print(f"  search_market_topic 跳过: {e}")
    else:
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
        test_orchestrator_logic()
        test_web_search()
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
