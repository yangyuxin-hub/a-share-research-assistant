"""Web Search Provider — 基于 ddgs (duckduckgo) 的实时网络搜索。

适用于：热点事件、板块动态、宏观政策、实时新闻等无法从结构化 API 获取的信息。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from ashare_research_assistant.core.models import NewsItem, SourceMeta

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source(provider: str) -> SourceMeta:
    return SourceMeta(
        provider=provider,
        fetched_at=_now_iso(),
        reliability="scraped",
    )


class WebSearchProvider:
    """基于 ddgs (DuckDuckGo) 的网络搜索 Provider。"""

    def __init__(self, max_results: int = 8) -> None:
        self._max_results = max_results
        self._client: Optional[object] = None

    def _get_client(self):
        """懒加载 ddgs 客户端。"""
        if self._client is None:
            from ddgs import DDGS

            self._client = DDGS()
        return self._client

    def search_news(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> list[NewsItem]:
        """搜索网络文本结果，返回 NewsItem 列表。

        Args:
            query: 搜索关键词，建议包含市场/板块/事件关键词
            max_results: 最大结果数，默认 self._max_results
        """
        max_results = max_results or self._max_results
        results: list[NewsItem] = []

        try:
            client = self._get_client()
            # 使用 text 搜索（news API 在部分地区不稳定）
            text_results = list(client.text(query, max_results=max_results))
        except Exception as e:
            logger.warning(f"ddgs 搜索失败 [{query}]: {e}")
            return []

        for item in text_results:
            try:
                results.append(NewsItem(
                    id=item.get("href", ""),
                    title=item.get("title", ""),
                    publish_time=_now_iso(),  # text 搜索不返回时间
                    outlet=item.get("source", ""),
                    url=item.get("href"),
                    summary=None,
                    related_symbols=[],
                    topic_tags=[query],
                    source=_source("ddgs"),
                ))
            except Exception as e:
                logger.debug(f"解析搜索结果失败: {e}")
                continue

        return results

    def search_market_topic(self, query: str) -> list[NewsItem]:
        """搜索市场/板块/宏观话题。

        这是 search_news 的别名，专用于市场热点场景。
        自动在 query 后追加"A股"以提升相关性。
        """
        # 增强 query 提升 A 股相关性
        enhanced = f"{query} A股" if "A股" not in query and "股票" not in query else query
        return self.search_news(enhanced)
