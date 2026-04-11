#!/usr/bin/env uv run python
"""精简测试 - 只测 RouterAgent 核心行为，跳过慢速 API 调用。"""

import sys, logging
sys.path.insert(0, "src")

from ashare_research_assistant.config.settings import settings
from ashare_research_assistant.agents.router import RouterAgent
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
import anthropic

logging.basicConfig(level=logging.WARNING)


def run():
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,
    )
    market = TushareMarketDataProvider(token=settings.tushare_token or None)
    router = RouterAgent(market_data_provider=market, anthropic_client=client)

    cases = [
        # (input, expected_intent, expect_clarification, description)
        ("贵州茅台最近怎么样", "single_stock_analysis", False, "知名全称"),
        ("平安", "clarification_required", True, "简称->多候选->追问"),
        ("600519", "single_stock_analysis", False, "数字代码"),
        ("招商银行和中国平安哪个更好", "stock_compare_or_followup", False, "比较意图"),
    ]

    passed = 0
    for inp, exp_intent, exp_clar, desc in cases:
        print(f"\n{'='*50}")
        print(f"[{desc}] {inp!r}")
        print("-" * 50)
        try:
            r = router.route(inp)
            print(f"  intent: {r.intent_type} (expected: {exp_intent})")
            print(f"  confidence: {r.confidence:.0%}")
            print(f"  symbols: {[(s.name, s.symbol) for s in r.resolved_entities]}")
            print(f"  clarify: {r.clarification_needed} (expected: {exp_clar})")

            ok_intent = r.intent_type == exp_intent
            ok_clar = r.clarification_needed == exp_clar

            if ok_intent and ok_clar:
                print("  PASS")
                passed += 1
            else:
                if not ok_intent:
                    print("  FAIL: intent mismatch")
                if not ok_clar:
                    print("  FAIL: clarification mismatch")
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"Result: {passed}/{len(cases)} passed")

    if passed == len(cases):
        print("All passed!")
    else:
        print(f"{len(cases) - passed} failed")
        sys.exit(1)


if __name__ == "__main__":
    run()
