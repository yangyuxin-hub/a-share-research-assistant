from abc import ABC, abstractmethod
from ashare_research_assistant.core.models import NewsItem


class NewsProvider(ABC):
    """新闻资讯 Provider 抽象接口。"""

    @abstractmethod
    def search_news(
        self,
        query: str,
        start_date: str,
        end_date: str,
        max_results: int = 20,
    ) -> list[NewsItem]:
        """通用新闻检索。"""

    @abstractmethod
    def search_company_news(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        max_results: int = 20,
    ) -> list[NewsItem]:
        """获取个股相关新闻。"""
