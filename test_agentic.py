#!/usr/bin/env uv run python
"""非交互式测试脚本 — 直接调用 RouterAgent + Orchestrator，验证核心链路。"""

import sys, logging
sys.path.insert(0, "src")

from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.core.models import SessionState
from ashare_research_assistant.agents.router import RouterAgent
from ashare_research_assistant.agents.tools import ToolExecutor
from ashare_research_assistant.agents.skills import select_skill
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.akshare import AKShareNewsProvider

import anthropic
from datetime import datetime, timezone

logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")

def ts():
    return datetime.now(timezone.utc).isoformat()


def test_router(user_input: str, session_ctx: str = None):
    print(f"\n{'='*60}")
    print(f"测试 Router: {user_input!r}")
    print("-" * 60)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url or None)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    router = RouterAgent(market_data_provider=market, anthropic_client=client)

    result = router.route(user_input, session_context=session_ctx)
    print(f"意图: {result.intent_type}")
    print(f"置信: {result.confidence:.0%}")
    print(f"标的: {[s.name for s in result.resolved_entities]}")
    print(f"追问: {result.clarification_needed}  {result.clarification_reason or ''}")
    return result


def test_stock_resolution(query: str):
    print(f"\n{'='*60}")
    print(f"测试 resolve_stock: {query!r}")
    print("-" * 60)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    executor = ToolExecutor(
        market_data=market,
        announcement=CninfoAnnouncementProvider(token=settings.tushare_token or None),
        news=AKShareNewsProvider(),
    )
    result = executor.execute("get_stock_profile", {"symbol": query})
    print(result[:300] if len(result) > 300 else result)
    return result


def test_price_snapshot(symbol: str):
    print(f"\n{'='*60}")
    print(f"测试 get_price_snapshot: {symbol}")
    print("-" * 60)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    executor = ToolExecutor(
        market_data=market,
        announcement=CninfoAnnouncementProvider(token=settings.tushare_token or None),
        news=AKShareNewsProvider(),
    )
    result = executor.execute("get_price_snapshot", {"symbol": symbol})
    print(result)
    return result


def test_skill_selection():
    print(f"\n{'='*60}")
    print("测试 Skill 选择")
    print("-" * 60)
    cases = [
        ("single_stock_analysis", "贵州茅台最近怎么样", 1),
        ("single_stock_analysis", "帮我分析一下平安", 2),
        ("stock_compare_or_followup", "茅台和五粮液哪个好", 2),
        ("hot_candidate_discovery", "今天有哪些涨停", 0),
        ("general_market_question", "大盘怎么样", 0),
    ]
    for intent, inp, count in cases:
        skill = select_skill(intent, inp, count)
        print(f"  {intent:35s} + {inp[:15]!r:20s} → {skill.name}")


def test_announcements(symbol: str):
    print(f"\n{'='*60}")
    print(f"测试 search_announcements: {symbol}")
    print("-" * 60)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    ann = CninfoAnnouncementProvider(token=settings.tushare_token or None)
    executor = ToolExecutor(
        market_data=market,
        announcement=ann,
        news=AKShareNewsProvider(),
    )
    result = executor.execute("search_announcements", {"symbol": symbol, "days": 30})
    print(result[:400] if len(result) > 400 else result)


def test_news(symbol: str):
    print(f"\n{'='*60}")
    print(f"测试 search_news: {symbol}")
    print("-" * 60)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    news = AKShareNewsProvider()
    executor = ToolExecutor(
        market_data=market,
        announcement=CninfoAnnouncementProvider(token=settings.tushare_token or None),
        news=news,
    )
    result = executor.execute("search_news", {"symbol": symbol, "days": 14})
    print(result[:400] if len(result) > 400 else result)


def test_resolve_stock_via_router(query: str):
    print(f"\n{'='*60}")
    print(f"测试 Router resolve_stock: {query!r}")
    print("-" * 60)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url or None)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    router = RouterAgent(market_data_provider=market, anthropic_client=client)
    result = router.route(query)
    print(f"意图: {result.intent_type} | 置信: {result.confidence:.0%}")
    print(f"标的: {[(s.name, s.symbol) for s in result.resolved_entities]}")
    print(f"追问: {result.clarification_needed} | {result.clarification_reason or '-'}")

    # "平安"（简称）应触发追问
    result_ambig = test_resolve_stock_via_router("平安")
    assert result_ambig.clarification_needed, \
        f"「平安」应触发追问！实际：clarification_needed={result_ambig.clarification_needed}"
    print(f"\n{'='*60}")
    print("测试股票比较意图")
    print("-" * 60)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url or None)
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    router = RouterAgent(market_data_provider=market, anthropic_client=client)

    result = router.route("招商银行和中国平安哪个更好")
    print(f"意图: {result.intent_type}")
    print(f"标的: {[(s.name, s.symbol) for s in result.resolved_entities]}")
    print(f"追问: {result.clarification_needed} | {result.clarification_reason or '-'}")


if __name__ == "__main__":
    print("=== A股投研助手 非交互测试 ===")
    print(f"API Key: {'已配置' if settings.anthropic_api_key else '未配置!'}")
    print(f"Tushare: {'已配置' if settings.tushare_token else '未配置'}")

    # 1. 股票解析
    test_resolve_stock_via_router("贵州茅台")
    test_resolve_stock_via_router("平安")
    test_resolve_stock_via_router("600519")

    # 2. 歧义检测（"平安" 应触发追问）
    result_ambig = test_resolve_stock_via_router("平安最近怎么样")
    assert result_ambig.clarification_needed, "「平安」应触发追问！"

    # 3. 无歧义单票
    # "贵州茅台" 不应触发追问（知名全称）
    result_single = test_resolve_stock_via_router("贵州茅台最近怎么样")
    assert result_single.intent_type == "single_stock_analysis", \
        f"「贵州茅台」应为 single_stock_analysis，实际：{result_single.intent_type}"
    assert len(result_single.resolved_entities) >= 1, \
        "应解析到贵州茅台"
    assert not result_single.clarification_needed, \
        "「贵州茅台最近怎么样」不应触发追问（知名全称）"

    # 4. 比较意图
    test_compare_intent()

    # 5. Skill 选择
    test_skill_selection()

    # 6. 工具执行
    test_price_snapshot("600519")
    test_announcements("600519")
    test_news("600519")

    print("\n" + "=" * 60)
    print("全部测试完成!")
