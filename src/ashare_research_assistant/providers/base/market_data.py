from abc import ABC, abstractmethod
from typing import Optional
from ashare_research_assistant.core.models import (
    StockIdentifier,
    StockProfile,
    PriceSnapshot,
    DailyBar,
    DailyFactor,
)


class MarketDataProvider(ABC):
    """市场行情与基础资料 Provider 抽象接口。

    Agent 层只依赖此接口，不直接碰第三方 SDK。
    """

    @abstractmethod
    def resolve_stock(self, query: str) -> list[StockIdentifier]:
        """通过股票代码或名称模糊匹配，返回候选标的列表。"""

    @abstractmethod
    def get_stock_profile(self, symbol: str) -> Optional[StockProfile]:
        """获取股票基础资料（行业、市场、上市信息等）。"""

    @abstractmethod
    def get_price_snapshot(self, symbol: str) -> Optional[PriceSnapshot]:
        """获取最新价格快照（当日或最近交易日）。"""

    @abstractmethod
    def get_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[DailyBar]:
        """获取区间日线行情数据（OHLCV）。"""

    @abstractmethod
    def get_daily_factors(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[DailyFactor]:
        """获取区间每日基础因子（换手率、量比、PE、PB、市值等）。"""
