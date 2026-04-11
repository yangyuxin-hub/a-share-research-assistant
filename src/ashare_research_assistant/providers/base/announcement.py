from abc import ABC, abstractmethod
from typing import Optional
from ashare_research_assistant.core.models import AnnouncementItem, AnnouncementDocument


class AnnouncementProvider(ABC):
    """上市公司公告 Provider 抽象接口。"""

    @abstractmethod
    def search_announcements(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        keywords: Optional[list[str]] = None,
        max_results: int = 20,
    ) -> list[AnnouncementItem]:
        """检索股票公告列表，支持时间范围和关键词过滤。"""

    @abstractmethod
    def get_announcement_detail(self, announcement_id: str) -> Optional[AnnouncementDocument]:
        """获取单条公告详情，含正文摘要和关键点。"""
