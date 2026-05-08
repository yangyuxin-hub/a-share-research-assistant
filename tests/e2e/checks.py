"""数据时效性 + 幻觉检测。"""

import re
from datetime import datetime, timezone
from typing import Optional


def check_data_freshness(tool_events: list[dict]) -> dict:
    """检查各工具返回的数据是否足够新鲜。"""
    today = datetime.now(timezone.utc).date()
    issues = []

    for event in tool_events:
        if event.get("event") != "tool_result":
            continue
        name = event.get("name", "")
        output = event.get("output", "")

        if name == "get_price_snapshot" and "无法获取" not in output:
            # 从 "## 600519 价格快照（20260423）" 提取日期
            m = re.search(r'价格快照.*?（(\d{8})）', output)
            if m:
                trade_date = datetime.strptime(m.group(1), "%Y%m%d").date()
                days_ago = (today - trade_date).days
                if days_ago > 5:
                    issues.append({
                        "tool": "get_price_snapshot",
                        "issue": f"trade_date {m.group(1)} 距今 {days_ago} 天，数据可能过期",
                        "days_ago": days_ago,
                    })

        if name == "search_news" and "无相关新闻" not in output:
            # 从输出里找所有日期，取最新的
            raw_dates = re.findall(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}|\d{4}-\d{2}-\d{2}|\d{8}', output)
            parsed = []
            for d in raw_dates:
                try:
                    if len(d) == 8:
                        parsed.append(datetime.strptime(d, "%Y%m%d").date())
                    elif len(d) == 10:
                        parsed.append(datetime.strptime(d, "%Y-%m-%d").date())
                    else:
                        parsed.append(datetime.strptime(d[:10], "%Y-%m-%d").date())
                except ValueError:
                    pass
            if parsed:
                latest = max(parsed)
                days_ago = (today - latest).days
                if days_ago > 14:
                    issues.append({
                        "tool": "search_news",
                        "issue": f"最新新闻距今 {days_ago} 天，可能是缓存数据",
                        "days_ago": days_ago,
                    })

        if name == "search_announcements" and "无公告" not in output:
            raw_dates = re.findall(r'\d{8}', output)
            parsed = []
            for d in raw_dates:
                try:
                    parsed.append(datetime.strptime(d, "%Y%m%d").date())
                except ValueError:
                    pass
            if parsed:
                latest = max(parsed)
                days_ago = (today - latest).days
                if days_ago > 60:
                    issues.append({
                        "tool": "search_announcements",
                        "issue": f"最新公告距今 {days_ago} 天",
                        "days_ago": days_ago,
                    })

    return {"ok": len(issues) == 0, "issues": issues}


def check_hallucination(tool_results: dict[str, str], opinion: Optional[dict]) -> list[str]:
    """检查观点卡里的数据是否有工具输出支撑。"""
    if opinion is None:
        return []

    warnings = []

    # 规则1：价格不可用，但存在非零价格目标
    # 仅当 get_price_snapshot=空 且 web_search 也无价格数字时才视为疑似幻觉
    price_out = tool_results.get("get_price_snapshot", "")
    web_out = tool_results.get("search_web", "")
    has_price_in_web = bool(web_out) and bool(re.search(r'\d{3,}\.\d+', web_out))
    if not price_out or "无法获取" in price_out:
        pt_low = opinion.get("price_target_low")
        pt_high = opinion.get("price_target_high")
        if pt_low and float(pt_low) > 0 and not has_price_in_web:
            warnings.append(
                f"价格数据不可用且 web 无价格信息，但存在价格目标 {pt_low}–{pt_high} → 疑似幻觉"
            )

    # 规则2：财务因子为空，但 core_drivers 出现具体 PE/PB 估值数字
    # 注意：净利润/营收等宏观财务数字可能来自 web_search，不视为幻觉
    # 只对 PE/PB 等需要有结构化数据支撑的估值指标做检查
    factors_out = tool_results.get("get_financial_factors", "")
    if not factors_out or "暂无" in factors_out:
        for driver in opinion.get("core_drivers", []):
            if re.search(r'\b(PE|PB|市盈|市净)\S*\s*\d+', driver):
                warnings.append(
                    f"财务数据不可用，core_drivers 出现估值数字: 「{driver[:60]}」"
                )
                break

    # 规则3：公告为空，但 thesis 提到具体公告事件
    # 仅当 announcement=空 且 web_search 也无相关关键词时才视为疑似幻觉
    # 因为定增/回购等信息也可能来自 web 搜索，不一定非要来自公告
    ann_out = tool_results.get("search_announcements", "")
    web_out = tool_results.get("search_web", "")
    if (not ann_out or "无公告" in ann_out) and (not web_out or len(web_out) < 50):
        thesis = opinion.get("thesis", "")
        for kw in ["定增", "回购", "增发"]:
            if kw in thesis:
                warnings.append(
                    f"公告数据为空且无 web 搜索结果，thesis 提及「{kw}」→ 疑似幻觉"
                )
                break

    # 规则4：新闻为空，但 market_narrative 描述了近期具体动态
    news_out = tool_results.get("search_news", "")
    if not news_out or "无相关新闻" in news_out:
        narrative = opinion.get("market_narrative", "")
        if len(narrative) > 20 and re.search(r'近期|最新|刚刚|昨日|本周|上周', narrative):
            warnings.append(
                "新闻数据为空，market_narrative 描述了近期动态 → 疑似幻觉"
            )

    return warnings
