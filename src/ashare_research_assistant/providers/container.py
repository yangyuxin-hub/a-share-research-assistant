"""Provider Container — 数据源的中央配置点。

替换数据源时只需修改这一个文件：
- 把某个实现类换成另一家的实现（如 TushareMarketDataProvider → BaostockMarketDataProvider）
- 或者组合多个 Provider 做 fallback

设计原则：
- __init__ 接受 settings 对象（而不是直接访问全局 settings），便于测试
- bundle() 返回 ProviderBundle，供 ToolExecutor / MainAgent 使用
- container 可作为单例缓存（见 web/app.py）
"""

import logging
from typing import Optional

from ashare_research_assistant.providers.akshare import AKShareNewsProvider
from ashare_research_assistant.providers.akshare.hotlist_provider import AKShareHotlistProvider
from ashare_research_assistant.providers.bundle import ProviderBundle
from ashare_research_assistant.providers.cninfo import CninfoAnnouncementProvider
from ashare_research_assistant.providers.tushare import TushareMarketDataProvider
from ashare_research_assistant.providers.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


class ProviderContainer:
    """中央 Provider 配置容器。

    替换数据源（如从 Tushare 换到 BaoStock）时，只改这里的实现类，
    其余层（tool handler、skill、agent）无感知。

    示例 — 新增数据源时：
        1. 实现 MarketDataProvider 接口
        2. 在此处替换/补充实例化逻辑
        3. 更新 bundle() 中对应字段
    """

    def __init__(self, settings) -> None:
        self.market = TushareMarketDataProvider(token=settings.tushare_token)
        self.announcement = CninfoAnnouncementProvider(
            token=settings.tushare_token or None
        )
        self.news = AKShareNewsProvider()
        self.hotlist = AKShareHotlistProvider()
        self.web_search = WebSearchProvider()
        logger.info("ProviderContainer 初始化完成")

    def bundle(self) -> ProviderBundle:
        """创建当前请求用的 ProviderBundle（轻量，无 IO）。"""
        return ProviderBundle(
            market=self.market,
            announcement=self.announcement,
            news=self.news,
            hotlist=self.hotlist,
            web_search=self.web_search,
        )
