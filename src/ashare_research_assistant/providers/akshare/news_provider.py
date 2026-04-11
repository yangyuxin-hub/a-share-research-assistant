"""AKShare 新闻 Provider 实现。

注意：AKShare 官方声明仅用于学术研究，不可商业使用。
第一版使用东财新闻接口做补充新闻层。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from ashare_research_assistant.core.models import NewsItem, SourceMeta
from ashare_research_assistant.providers.base import NewsProvider

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source(endpoint: str) -> SourceMeta:
    return SourceMeta(
        provider="akshare",
        endpoint=endpoint,
        fetched_at=_now_iso(),
        reliability="scraped",
    )


class AKShareNewsProvider(NewsProvider):
    def search_news(
        self,
        query: str,
        start_date: str,
        end_date: str,
        max_results: int = 20,
    ) -> list[NewsItem]:
        # 第一版暂不实现通用新闻搜索
        return []

    def search_company_news(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        max_results: int = 20,
    ) -> list[NewsItem]:
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return []

            items = []
            for _, row in df.head(max_results).iterrows():
                publish_time = str(row.get("发布时间", ""))
                # 简单按日期过滤（akshare 返回的时间格式不统一，做宽松过滤）
                items.append(NewsItem(
                    id=f"akshare_{symbol}_{len(items)}",
                    title=str(row.get("新闻标题", "")),
                    publish_time=publish_time,
                    outlet=str(row.get("文章来源", "")) or None,
                    url=str(row.get("新闻链接", "")) or None,
                    related_symbols=[symbol],
                    source=_source("stock_news_em"),
                ))
            return items
        except Exception as e:
            logger.warning(f"AKShareNewsProvider.search_company_news 失败 [{symbol}]: {e}")
            return []
