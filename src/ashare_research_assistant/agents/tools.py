"""投研工具层 — LLM 可调用的原子数据工具。

每个工具只做一件事：从 provider 取数据，格式化成 LLM 可读的字符串。
不含任何 LLM 调用，不做业务判断。
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ashare_research_assistant.core.models import StockIdentifier
from ashare_research_assistant.providers.base import (
    AnnouncementProvider,
    MarketDataProvider,
    NewsProvider,
)

try:
    from ashare_research_assistant.providers.base import HotlistProvider
    _HAS_HOTLIST = True
except ImportError:
    _HAS_HOTLIST = False

logger = logging.getLogger(__name__)


# ── 工具 Schema 定义 ──────────────────────────────────────────────────────────

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
        "搜索网络获取实时市场信息。适用场景：热点事件对股市的影响（如特朗普关税政策）、"
        "板块动态、宏观政策解读、实时新闻。当用户询问的事件不在数据库中时应优先使用此工具。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "搜索关键词，建议包含事件和A股关键词。"
                    "示例：「特朗普关税 A股影响」「AI算力板块最新动态」"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "最多返回新闻条数，默认 6",
                "default": 6,
            },
        },
        "required": ["query"],
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

# 各 Skill 可用的工具集（不含 commit_opinion，由 Skill 层统一追加）
TOOLS_FULL_RESEARCH = [
    TOOL_GET_STOCK_PROFILE,
    TOOL_GET_PRICE_SNAPSHOT,
    TOOL_GET_DAILY_BARS,
    TOOL_GET_FINANCIAL_FACTORS,
    TOOL_SEARCH_ANNOUNCEMENTS,
    TOOL_SEARCH_NEWS,
]

TOOLS_QUICK_CHECK = [
    TOOL_GET_STOCK_PROFILE,
    TOOL_GET_PRICE_SNAPSHOT,
    TOOL_GET_FINANCIAL_FACTORS,
]

TOOLS_MARKET_OVERVIEW = [
    TOOL_GET_HOT_LIST,
    TOOL_WEB_SEARCH,
]


# ── Tool Executor ─────────────────────────────────────────────────────────────

class ToolExecutor:
    """执行 LLM 调用的工具，返回格式化字符串。

    持有 provider 引用，不含 LLM 调用。
    额外维护 last_price 供 commit_opinion 处理层读取。
    """

    def __init__(
        self,
        market_data: MarketDataProvider,
        announcement: AnnouncementProvider,
        news: NewsProvider,
        hotlist: Optional[object] = None,  # HotlistProvider
        web_search: Optional[object] = None,
    ) -> None:
        self._market = market_data
        self._ann = announcement
        self._news = news
        self._hotlist = hotlist
        self._web_search = web_search
        self.last_price: Optional[float] = None  # 供外部读取

    def execute(self, tool_name: str, tool_input: dict) -> str:
        """分发工具调用，返回 LLM 可读的结果字符串。"""
        handlers = {
            "get_stock_profile": self._get_stock_profile,
            "get_price_snapshot": self._get_price_snapshot,
            "get_daily_bars": self._get_daily_bars,
            "get_financial_factors": self._get_financial_factors,
            "search_announcements": self._search_announcements,
            "search_news": self._search_news,
            "get_hot_list": self._get_hot_list,
            "search_web": self._search_web,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return f"未知工具：{tool_name}"
        try:
            return handler(tool_input)
        except Exception as e:
            logger.error(f"工具执行失败 [{tool_name}]: {e}")
            return f"工具执行失败：{e}"

    # ── 各工具实现 ──────────────────────────────────────────────────────────────

    def _get_stock_profile(self, inp: dict) -> str:
        symbol = inp["symbol"]
        profile = self._market.get_stock_profile(symbol)
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

    def _get_price_snapshot(self, inp: dict) -> str:
        symbol = inp["symbol"]
        snap = self._market.get_price_snapshot(symbol)
        if not snap:
            return f"无法获取 {symbol} 价格数据"
        self.last_price = snap.current_price
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

    def _get_daily_bars(self, inp: dict) -> str:
        symbol = inp["symbol"]
        days = int(inp.get("days", 20))
        end_date, start_date = self._date_range(days)
        bars = self._market.get_daily_bars(symbol, start_date, end_date)
        if not bars:
            return f"{symbol} 区间 {start_date}~{end_date} 无日线数据"
        lines = [f"## {symbol} 近 {len(bars)} 交易日行情"]
        for b in bars[-15:]:
            pct = f"{b.pct_change:+.2f}%" if b.pct_change is not None else "N/A"
            vol = f"{b.volume/10000:.0f}万" if b.volume else "N/A"
            lines.append(f"  {b.trade_date}  收:{b.close:.2f}  {pct}  量:{vol}")
        # 简单趋势统计
        closes = [b.close for b in bars]
        if len(closes) >= 5:
            chg_5d = (closes[-1] - closes[-5]) / closes[-5] * 100
            lines.append(f"近 5 交易日涨跌：{chg_5d:+.1f}%")
        return "\n".join(lines)

    def _get_financial_factors(self, inp: dict) -> str:
        symbol = inp["symbol"]
        days = int(inp.get("days", 20))
        end_date, start_date = self._date_range(days)
        factors = self._market.get_daily_factors(symbol, start_date, end_date)
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
        if lf.circ_market_value:
            lines.append(f"流通市值：{lf.circ_market_value/1e8:.1f} 亿")
        if lf.turnover_rate:
            lines.append(f"换手率：{lf.turnover_rate:.2f}%")
        if lf.volume_ratio:
            lines.append(f"量比：{lf.volume_ratio:.2f}")
        return "\n".join(lines)

    def _search_announcements(self, inp: dict) -> str:
        symbol = inp["symbol"]
        days = int(inp.get("days", 30))
        max_results = int(inp.get("max_results", 10))
        end_date, start_date = self._date_range(days)
        items = self._ann.search_announcements(
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

    def _search_news(self, inp: dict) -> str:
        symbol = inp["symbol"]
        days = int(inp.get("days", 14))
        max_results = int(inp.get("max_results", 10))
        end_date, start_date = self._date_range(days)
        try:
            items = self._news.search_company_news(
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

    def _get_hot_list(self, inp: dict) -> str:
        if not self._hotlist:
            return "热门榜单功能暂未启用"
        list_type = inp.get("list_type", "hot")
        limit = int(inp.get("limit", 20))
        try:
            items = self._hotlist.get_hot_stocks(list_type=list_type, limit=limit)
        except Exception as e:
            return f"热门榜单获取失败：{e}"
        if not items:
            return "暂无榜单数据"
        lines = [f"## 今日{list_type}榜（TOP {len(items)}）"]
        for i, item in enumerate(items[:limit], 1):
            pct = f"{item.pct_change:+.2f}%" if item.pct_change is not None else ""
            lines.append(f"{i:2d}. {item.name}（{item.symbol}）{pct}  {item.reason or ''}")
        return "\n".join(lines)

    def _search_web(self, inp: dict) -> str:
        if not self._web_search:
            return "网络搜索功能暂未启用"
        query = inp.get("query", "")
        max_results = int(inp.get("max_results", 6))
        if not query:
            return "请提供搜索关键词"
        try:
            items = self._web_search.search_news(query, max_results=max_results)
        except Exception as e:
            logger.warning(f"网络搜索失败 [{query}]: {e}")
            return f"网络搜索失败：{e}"
        if not items:
            return f"未找到「{query}」相关实时信息"
        lines = [f"## 网络搜索：「{query}」（{len(items)} 条）"]
        for n in items:
            outlet = n.outlet or ""
            date = n.publish_time[:10] if n.publish_time else ""
            lines.append(f"- [{date}][{outlet}] {n.title}")
            if n.summary and n.summary != n.title:
                lines.append(f"  {n.summary[:120]}")
        return "\n".join(lines)

    def _search_web(self, inp: dict) -> str:
        if not self._web_search:
            return "网络搜索功能暂未启用"
        query = inp.get("query", "")
        max_results = int(inp.get("max_results", 6))
        if not query:
            return "search_web 需要提供 query 参数"
        try:
            items = self._web_search.search_news(query, max_results=max_results)
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

    # ── 工具函数 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _date_range(days: int) -> tuple[str, str]:
        """返回 (end_date, start_date) 字符串，格式 YYYYMMDD。"""
        now = datetime.now(timezone.utc)
        end = now.strftime("%Y%m%d")
        start = (now - timedelta(days=days)).strftime("%Y%m%d")
        return end, start
