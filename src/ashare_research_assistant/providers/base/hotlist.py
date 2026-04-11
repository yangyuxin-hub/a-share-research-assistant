from abc import ABC, abstractmethod
from typing import Optional
from ashare_research_assistant.core.models import HotStockItem


class HotlistProvider(ABC):
    """市场热门与异动数据 Provider 抽象接口。"""

    @abstractmethod
    def get_hot_stocks(
        self,
        date: Optional[str] = None,
        top_n: int = 20,
    ) -> list[HotStockItem]:
        """获取当日热门股票榜单。"""

    @abstractmethod
    def get_limit_up_pool(self, date: Optional[str] = None) -> list[HotStockItem]:
        """获取涨停板池。"""
