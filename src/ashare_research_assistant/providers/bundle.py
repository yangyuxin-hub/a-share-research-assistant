"""Provider Bundle — 单次请求中所有 Provider 的类型化容器。

使用场景：
- ToolRegistry 调用工具 handler 时传入
- MainAgent 初始化时从 ProviderContainer.bundle() 获取
- 单元测试时可注入 mock provider

替换数据源：在 ProviderContainer 里换实现类，bundle() 接口不变。
"""

from dataclasses import dataclass
from typing import Optional

from ashare_research_assistant.providers.base import (
    AnnouncementProvider,
    HotlistProvider,
    MarketDataProvider,
    NewsProvider,
)


@dataclass
class ProviderBundle:
    """强类型的 Provider 集合，按需传给工具 handler。"""

    market: MarketDataProvider
    announcement: AnnouncementProvider
    news: NewsProvider
    hotlist: Optional[HotlistProvider] = None
    web_search: Optional[object] = None  # WebSearchProvider（无抽象基类）
