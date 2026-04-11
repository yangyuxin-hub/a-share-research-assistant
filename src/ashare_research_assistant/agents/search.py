"""Search Agent.

负责：拉取公告和新闻，组织成 EvidenceBundle。
"""

import logging
from datetime import datetime, timezone

from ashare_research_assistant.core.models import (
    AnnouncementItem,
    Citation,
    EvidenceBundle,
    EvidenceItem,
    StockIdentifier,
)
from ashare_research_assistant.providers.base import AnnouncementProvider, NewsProvider

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SearchAgent:
    def __init__(
        self,
        announcement_provider: AnnouncementProvider,
        news_provider: NewsProvider,
    ) -> None:
        self._ann = announcement_provider
        self._news = news_provider

    def collect_evidence(
        self,
        symbol: StockIdentifier,
        start_date: str,
        end_date: str,
        max_announcements: int = 10,
        max_news: int = 10,
    ) -> EvidenceBundle:
        items: list[EvidenceItem] = []
        gaps: list[str] = []

        # 公告证据
        announcements = self._ann.search_announcements(
            symbol=symbol.symbol,
            start_date=start_date,
            end_date=end_date,
            max_results=max_announcements,
        )
        if announcements:
            for ann in announcements:
                items.append(self._ann_to_evidence(ann, symbol.symbol))
        else:
            gaps.append(f"{start_date} 至 {end_date} 期间未找到公告")

        # 新闻证据
        try:
            news_items = self._news.search_company_news(
                symbol=symbol.symbol,
                start_date=start_date,
                end_date=end_date,
                max_results=max_news,
            )
            for news in news_items:
                items.append(self._news_to_evidence(news, symbol.symbol))
        except Exception as e:
            logger.warning(f"新闻检索失败 [{symbol.symbol}]: {e}")
            gaps.append("新闻数据获取失败")

        return EvidenceBundle(
            symbol=symbol.symbol,
            items=items,
            gaps=gaps,
            contradictory_signals=[],
            last_updated_at=_now_iso(),
        )

    def _ann_to_evidence(self, ann: AnnouncementItem, symbol: str) -> EvidenceItem:
        return EvidenceItem(
            kind="announcement",
            title=ann.title,
            summary=ann.summary or ann.title,
            symbol=symbol,
            event_time=ann.publish_time,
            factuality="fact",
            citations=[
                Citation(
                    source_name=ann.source.provider,
                    url=ann.url,
                    document_id=ann.id,
                    published_at=ann.publish_time,
                )
            ],
        )

    def _news_to_evidence(self, news, symbol: str) -> EvidenceItem:
        return EvidenceItem(
            kind="news",
            title=news.title,
            summary=news.summary or news.title,
            symbol=symbol,
            event_time=news.publish_time,
            factuality="derived",
            citations=[
                Citation(
                    source_name=news.outlet or news.source.provider,
                    url=news.url,
                    document_id=news.id,
                    published_at=news.publish_time,
                )
            ],
        )
