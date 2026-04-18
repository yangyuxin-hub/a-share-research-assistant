"""投研工具层 — LLM 可调用的原子数据工具。

架构变化（v2）：
- 每个工具通过 @tool_registry.register(SCHEMA) 自注册，不再维护手动 dispatch dict
- 新增工具：写一个 handler 函数 + 加一行装饰器，无需改其他代码
- ToolExecutor 变为薄包装层（向后兼容 MainAgent），仅维护 last_price 等请求级状态
- ProviderBundle 统一传递，handler 内用 providers.market / providers.news 等访问数据源

Handler 签名：
    def _handle_xxx(inp: dict, providers: ProviderBundle, ctx: dict) -> str
    ctx["last_price"] 由 get_price_snapshot handler 写入，供 commit_opinion 读取。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ashare_research_assistant.agents.tool_registry import tool_registry
from ashare_research_assistant.providers.base import (
    AnnouncementProvider,
    MarketDataProvider,
    NewsProvider,
)
from ashare_research_assistant.providers.bundle import ProviderBundle

logger = logging.getLogger(__name__)


# ── 工具日期工具函数 ──────────────────────────────────────────────────────────

def _date_range(days: int) -> tuple[str, str]:
    """返回 (end_date, start_date)，格式 YYYYMMDD。"""
    now = datetime.now(timezone.utc)
    end = now.strftime("%Y%m%d")
    start = (now - timedelta(days=days)).strftime("%Y%m%d")
    return end, start


# ── Tool Schema 定义 ──────────────────────────────────────────────────────────

TOOL_GET_STOCK_PROFILE = {
    "name": "get_stock_profile",
    "description": "获取公司基础资料：行业、市场、上市日期、业务简介等。分析任何股票时应最先调用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码，如 600519"},
        },
        "required": ["symbol"],
    },
}

TOOL_GET_PRICE_SNAPSHOT = {
    "name": "get_price_snapshot",
    "description": "获取最新价格快照：当前价、涨跌幅、换手率（当日或最近交易日）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码"},
        },
        "required": ["symbol"],
    },
}

TOOL_GET_DAILY_BARS = {
    "name": "get_daily_bars",
    "description": "获取历史日线行情（OHLCV + 涨跌幅）。用于判断近期趋势、振幅、成交量变化。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码"},
            "days": {
                "type": "integer",
                "description": "回溯自然日数，默认 20（约 15 个交易日）",
                "default": 20,
            },
        },
        "required": ["symbol"],
    },
}

TOOL_GET_FINANCIAL_FACTORS = {
    "name": "get_financial_factors",
    "description": "获取最新估值因子：PE(TTM)、PB、总市值、换手率、量比等。用于估值判断和拥挤度评估。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码"},
            "days": {
                "type": "integer",
                "description": "回溯自然日数，默认 20",
                "default": 20,
            },
        },
        "required": ["symbol"],
    },
}

TOOL_SEARCH_ANNOUNCEMENTS = {
    "name": "search_announcements",
    "description": "搜索公司近期公告（定期报告、重大事项、股权变动等）。获取事件驱动信息的首选工具。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码"},
            "days": {
                "type": "integer",
                "description": "回溯自然日数，默认 30",
                "default": 30,
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回条数，默认 10",
                "default": 10,
            },
        },
        "required": ["symbol"],
    },
}

TOOL_SEARCH_NEWS = {
    "name": "search_news",
    "description": "搜索公司相关财经新闻。获取市场情绪和舆论信息。",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "股票代码"},
            "days": {
                "type": "integer",
                "description": "回溯自然日数，默认 14",
                "default": 14,
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回条数，默认 10",
                "default": 10,
            },
        },
        "required": ["symbol"],
    },
}

TOOL_GET_HOT_LIST = {
    "name": "get_hot_list",
    "description": "获取今日市场热门股票榜单（涨停、涨幅榜、资金流入榜等）。用于市场概览和热点发现。",
    "input_schema": {
        "type": "object",
        "properties": {
            "list_type": {
                "type": "string",
                "enum": ["limit_up", "top_gainers", "hot"],
                "description": "榜单类型：limit_up=涨停，top_gainers=涨幅榜，hot=热门榜",
                "default": "hot",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量，默认 20",
                "default": 20,
            },
        },
        "required": [],
    },
}

TOOL_WEB_SEARCH = {
    "name": "search_web",
    "description": (
        "搜索网络获取实时市场信息。用于：热点事件影响、板块动态、宏观政策、实时新闻。"
        "当用户询问的主题无法通过结构化数据回答时（如「特朗普关税影响」「AI板块最新动态」），"
        "应优先调用此工具获取实时信息。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "搜索关键词。建议包含具体事件/主题词。"
                    "例如：「特朗普关税 A股影响 2026」「AI算力板块最新动态」"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回条数，默认 8",
                "default": 8,
            },
        },
        "required": ["query"],
    },
}

TOOL_COMMIT_OPINION = {
    "name": "commit_opinion",
    "description": (
        "数据收集和分析完成后，提交最终投研观点。"
        "调用此工具意味着分析结束，请确保已收集足够数据。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {
                "type": "string",
                "enum": ["bullish", "neutral", "bearish"],
                "description": "多空立场",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "置信度",
            },
            "one_liner": {
                "type": "string",
                "description": "一句话结论，20 字以内，结论优先",
            },
            "market_narrative": {
                "type": "string",
                "description": "市场当前对该股的主叙事，1-2 句",
            },
            "thesis": {
                "type": "string",
                "description": "核心投资逻辑，2-3 句",
            },
            "core_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "核心驱动因素，3-5 条，每条须有数据或事件支撑",
            },
            "key_risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主要风险，2-4 条",
            },
            "debate_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "多空分歧点，1-3 条",
            },
            "watch_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "后续观察点，1-3 条",
            },
            "price_target_low": {
                "type": "number",
                "description": "预期价格区间下沿",
            },
            "price_target_high": {
                "type": "number",
                "description": "预期价格区间上沿",
            },
            "horizon_label": {
                "type": "string",
                "enum": ["1-3d", "1w", "2w", "custom"],
                "description": "判断期限",
            },
            "anchor_summary": {
                "type": "string",
                "description": "价位锚定依据摘要，50 字以内",
            },
            "evidence_chain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "interpretation": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": ["support", "oppose", "mixed"],
                        },
                    },
                    "required": ["title", "interpretation", "direction"],
                },
                "description": "关键证据链，最多 5 条",
            },
        },
        "required": [
            "stance", "confidence", "one_liner", "thesis",
            "core_drivers", "key_risks", "horizon_label",
        ],
    },
}


# ── Tool Handler 注册 ─────────────────────────────────────────────────────────
# 每个函数通过 @tool_registry.register(SCHEMA) 自注册。
# 新增工具：复制一个 handler 模板，改 schema 和逻辑，无需改其他文件。

@tool_registry.register(TOOL_GET_STOCK_PROFILE)
def _handle_get_stock_profile(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    symbol = inp["symbol"]
    profile = providers.market.get_stock_profile(symbol)
    if not profile:
        return f"未找到 {symbol} 的公司资料"
    si = profile.identifier
    lines = [f"## {si.name}（{si.symbol}）基础资料"]
    if si.industry:
        lines.append(f"行业：{si.industry}")
    if profile.market:
        lines.append(f"市场：{profile.market}")
    if profile.area:
        lines.append(f"地区：{profile.area}")
    if profile.list_date:
        lines.append(f"上市日期：{profile.list_date}")
    if profile.concept_tags:
        lines.append(f"概念标签：{', '.join(profile.concept_tags[:8])}")
    if profile.business_summary:
        lines.append(f"业务简介：{profile.business_summary[:150]}")
    return "\n".join(lines)


@tool_registry.register(TOOL_GET_PRICE_SNAPSHOT)
def _handle_get_price_snapshot(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    symbol = inp["symbol"]
    snap = providers.market.get_price_snapshot(symbol)
    if not snap:
        return f"无法获取 {symbol} 价格数据"
    ctx["last_price"] = snap.current_price  # 供 commit_opinion 读取
    lines = [f"## {symbol} 价格快照（{snap.trade_date}）"]
    lines.append(f"当前价：{snap.current_price:.2f}")
    if snap.prev_close:
        lines.append(f"昨收：{snap.prev_close:.2f}")
    if snap.pct_change is not None:
        lines.append(f"涨跌幅：{snap.pct_change:+.2f}%")
    if snap.high and snap.low:
        lines.append(f"今日区间：{snap.low:.2f} ~ {snap.high:.2f}")
    turnover = getattr(snap, "turnover_rate", None)
    if turnover is not None:
        lines.append(f"换手率：{turnover:.2f}%")
    return "\n".join(lines)


@tool_registry.register(TOOL_GET_DAILY_BARS)
def _handle_get_daily_bars(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    symbol = inp["symbol"]
    days = int(inp.get("days", 20))
    end_date, start_date = _date_range(days)
    bars = providers.market.get_daily_bars(symbol, start_date, end_date)
    if not bars:
        return f"{symbol} 区间 {start_date}~{end_date} 无日线数据"
    lines = [f"## {symbol} 近 {len(bars)} 交易日行情"]
    for b in bars[-15:]:
        pct = f"{b.pct_change:+.2f}%" if b.pct_change is not None else "N/A"
        vol = f"{b.volume/10000:.0f}万" if b.volume else "N/A"
        lines.append(f"  {b.trade_date}  收:{b.close:.2f}  {pct}  量:{vol}")
    closes = [b.close for b in bars]
    if len(closes) >= 5:
        chg_5d = (closes[-1] - closes[-5]) / closes[-5] * 100
        lines.append(f"近 5 交易日涨跌：{chg_5d:+.1f}%")
    return "\n".join(lines)


@tool_registry.register(TOOL_GET_FINANCIAL_FACTORS)
def _handle_get_financial_factors(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    symbol = inp["symbol"]
    days = int(inp.get("days", 20))
    end_date, start_date = _date_range(days)
    factors = providers.market.get_daily_factors(symbol, start_date, end_date)
    if not factors:
        return f"{symbol} 暂无估值因子数据"
    lf = factors[-1]
    lines = [f"## {symbol} 最新估值因子（{lf.trade_date}）"]
    if lf.pe_ttm:
        lines.append(f"PE(TTM)：{lf.pe_ttm:.1f}")
    if lf.pb:
        lines.append(f"PB：{lf.pb:.2f}")
    if lf.total_market_value:
        lines.append(f"总市值：{lf.total_market_value/1e8:.1f} 亿")
    if lf.float_market_value:
        lines.append(f"流通市值：{lf.float_market_value/1e8:.1f} 亿")
    if lf.turnover_rate:
        lines.append(f"换手率：{lf.turnover_rate:.2f}%")
    if lf.volume_ratio:
        lines.append(f"量比：{lf.volume_ratio:.2f}")
    return "\n".join(lines)


@tool_registry.register(TOOL_SEARCH_ANNOUNCEMENTS)
def _handle_search_announcements(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    symbol = inp["symbol"]
    days = int(inp.get("days", 30))
    max_results = int(inp.get("max_results", 10))
    end_date, start_date = _date_range(days)
    items = providers.announcement.search_announcements(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        max_results=max_results,
    )
    if not items:
        return f"{symbol} 近 {days} 天无公告"
    lines = [f"## {symbol} 近期公告（{len(items)} 条）"]
    for ann in items:
        lines.append(f"- [{ann.publish_time or ''}] {ann.title}")
        if ann.summary and ann.summary != ann.title:
            lines.append(f"  摘要：{ann.summary[:100]}")
    return "\n".join(lines)


@tool_registry.register(TOOL_SEARCH_NEWS)
def _handle_search_news(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    symbol = inp["symbol"]
    days = int(inp.get("days", 14))
    max_results = int(inp.get("max_results", 10))
    end_date, start_date = _date_range(days)
    try:
        items = providers.news.search_company_news(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            max_results=max_results,
        )
    except Exception as e:
        return f"新闻获取失败：{e}"
    if not items:
        return f"{symbol} 近 {days} 天无相关新闻"
    lines = [f"## {symbol} 近期新闻（{len(items)} 条）"]
    for n in items:
        outlet = getattr(n, "outlet", "") or ""
        lines.append(f"- [{n.publish_time or ''}][{outlet}] {n.title}")
        if n.summary and n.summary != n.title:
            lines.append(f"  {n.summary[:80]}")
    return "\n".join(lines)


@tool_registry.register(TOOL_GET_HOT_LIST)
def _handle_get_hot_list(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    list_type = inp.get("list_type", "hot")
    limit = int(inp.get("limit", 20))

    if providers.hotlist:
        try:
            if list_type == "limit_up":
                items = providers.hotlist.get_limit_up_pool()[:limit]
            else:
                items = providers.hotlist.get_hot_stocks(top_n=limit)
            if items:
                lines = [f"## 今日{list_type}榜（TOP {len(items)}）"]
                for i, item in enumerate(items, 1):
                    pct = item.momentum_score
                    pct_str = f"{pct:+.2f}%" if pct is not None else ""
                    lines.append(f"{i:2d}. {item.name}（{item.symbol}）{pct_str}")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"akshare 热榜获取失败，降级到网络搜索: {e}")

    if providers.web_search:
        try:
            query = "今日A股热门股票涨幅榜" if list_type == "limit_up" else "今日A股热门股票排行榜"
            items = providers.web_search.search_news(query, max_results=limit)
            if items:
                lines = [f"## 今日{list_type}榜（网络搜索结果）"]
                for i, n in enumerate(items[:limit], 1):
                    lines.append(f"{i:2d}. {n.title[:40]}")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"网络搜索降级也失败: {e}")

    return "热门榜单功能暂未启用，请尝试直接查询具体股票代码"


@tool_registry.register(TOOL_COMMIT_OPINION)
def _handle_commit_opinion(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    # commit_opinion 由 agent 层截获处理，此 handler 不会被实际调用。
    # 注册的目的是让 tool_registry.get_schemas(["commit_opinion"]) 能取到 schema。
    return "已提交"


@tool_registry.register(TOOL_WEB_SEARCH)
def _handle_search_web(inp: dict, providers: ProviderBundle, ctx: dict) -> str:
    if not providers.web_search:
        return "网络搜索功能暂未启用"
    query = inp.get("query", "")
    max_results = int(inp.get("max_results", 6))
    if not query:
        return "search_web 需要提供 query 参数"
    try:
        items = providers.web_search.search_news(query, max_results=max_results)
    except Exception as e:
        logger.warning(f"search_web 失败 [{query}]: {e}")
        return f"搜索失败：{e}"
    if not items:
        return f"未找到「{query}」相关实时资讯"
    lines = [f"## 实时资讯：{query}（{len(items)} 条）"]
    for n in items:
        outlet = n.outlet or ""
        lines.append(f"- [{n.publish_time or ''}][{outlet}] {n.title}")
        if n.summary and n.summary != n.title:
            lines.append(f"  {n.summary[:100]}")
    return "\n".join(lines)


# ── Tool 分组（Skill 引用工具名称列表，schema 从 tool_registry 取）────────────
# 新增工具后，把工具名加到对应分组即可；Skill 的 tools_with_commit 自动更新。

TOOLS_FULL_RESEARCH_NAMES = [
    "get_stock_profile",
    "get_price_snapshot",
    "get_daily_bars",
    "get_financial_factors",
    "search_announcements",
    "search_news",
]

TOOLS_QUICK_CHECK_NAMES = [
    "get_stock_profile",
    "get_price_snapshot",
    "get_financial_factors",
]

TOOLS_MARKET_OVERVIEW_NAMES = [
    "get_hot_list",
    "search_web",
]

# 向后兼容：旧代码 import TOOLS_FULL_RESEARCH 等 list[dict] 常量
# 这些在模块加载后（所有 handler 已注册）才求值，值正确
TOOLS_FULL_RESEARCH = tool_registry.get_schemas(TOOLS_FULL_RESEARCH_NAMES)
TOOLS_QUICK_CHECK = tool_registry.get_schemas(TOOLS_QUICK_CHECK_NAMES)
TOOLS_MARKET_OVERVIEW = tool_registry.get_schemas(TOOLS_MARKET_OVERVIEW_NAMES)


# ── ToolExecutor（薄包装层，向后兼容 MainAgent）──────────────────────────────

class ToolExecutor:
    """请求级工具执行器。

    职责：
    - 持有当前请求的 ProviderBundle
    - 维护请求级 side-effect（last_price 等）
    - 委托 tool_registry.execute() 完成实际路由和调用

    MainAgent 用法（不变）：
        executor = ToolExecutor(market_data=..., announcement=..., news=...)
        result = executor.execute("get_price_snapshot", {"symbol": "600519"})
        price = executor.last_price
    """

    def __init__(
        self,
        market_data: MarketDataProvider,
        announcement: AnnouncementProvider,
        news: NewsProvider,
        hotlist: Optional[object] = None,
        web_search: Optional[object] = None,
    ) -> None:
        self._bundle = ProviderBundle(
            market=market_data,
            announcement=announcement,
            news=news,
            hotlist=hotlist,
            web_search=web_search,
        )
        self._ctx: dict = {}  # 请求级 side-effect 字典

    @property
    def last_price(self) -> Optional[float]:
        """最后一次 get_price_snapshot 的价格，供 commit_opinion 使用。"""
        return self._ctx.get("last_price")

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """路由到 tool_registry，返回 LLM 可读字符串。"""
        return tool_registry.execute(tool_name, tool_input, self._bundle, self._ctx)
