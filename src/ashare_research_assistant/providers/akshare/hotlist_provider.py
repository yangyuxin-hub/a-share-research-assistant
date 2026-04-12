"""AKShare 热门榜单 Provider — 基于 akshare 实现 HotlistProvider 接口。"""

import logging
from datetime import datetime, timezone
from typing import Optional

import akshare as ak
import pandas as pd

from ashare_research_assistant.core.models import HotStockItem, SourceMeta

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_code_to_symbol(ts_code: str) -> str:
    """将 tushare 格式 ts_code（如 600519.SH）转为 6 位代码。"""
    if not ts_code:
        return ""
    return ts_code.split(".")[0] if "." in ts_code else ts_code


def _stock_hot_to_items(df: pd.DataFrame, source_name: str) -> list[HotStockItem]:
    """将 akshare 热门榜单 DataFrame 转换为 HotStockItem 列表。"""
    # 东方财富热门榜列名：当前排名、代码、股票名称、现价、涨跌幅、热度
    items = []
    for _, row in df.head(20).iterrows():
        try:
            items.append(HotStockItem(
                symbol=str(row.iloc[1]) if len(row) > 1 else "",
                name=str(row.iloc[2]) if len(row) > 2 else "",
                heat_score=float(row.iloc[-1]) if len(row) > 3 else 0.0,
                momentum_score=float(row.iloc[4]) if len(row) > 4 and str(row.iloc[4]).replace(".", "", 1).replace("-", "", 1).isdigit() else None,
                narrative=None,
                reasons=[],
                related_themes=[],
                source=SourceMeta(
                    provider="akshare",
                    endpoint=source_name,
                    fetched_at=_now_iso(),
                    reliability="scraped",
                ),
            ))
        except Exception:
            continue
    return items


def _zt_pool_to_items(df: pd.DataFrame, source_name: str) -> list[HotStockItem]:
    """将 akshare 涨停池 DataFrame 转换为 HotStockItem 列表。"""
    items = []
    for _, row in df.iterrows():
        try:
            symbol = str(row.get("代码", "")) if "代码" in row.index else str(row.iloc[1])
            name = str(row.get("名称", "")) if "名称" in row.index else str(row.iloc[2])
            pct = row.get("涨跌幅", 0)
            if isinstance(pct, str):
                pct = float(pct.replace("%", "")) if pct else 0
            items.append(HotStockItem(
                symbol=symbol,
                name=name,
                heat_score=float(pct) if pct else 0.0,
                momentum_score=float(pct) if pct else None,
                narrative=None,
                reasons=[],
                related_themes=[],
                source=SourceMeta(
                    provider="akshare",
                    endpoint=source_name,
                    fetched_at=_now_iso(),
                    reliability="scraped",
                ),
            ))
        except Exception:
            continue
    return items


class AKShareHotlistProvider:
    """使用 akshare 获取热门股票和涨停板池。"""

    def get_hot_stocks(
        self,
        date: Optional[str] = None,
        top_n: int = 20,
    ) -> list[HotStockItem]:
        """获取东方财富热门股票榜单。"""
        try:
            df = ak.stock_hot_rank_em()
            items = _stock_hot_to_items(df, "stock_hot_rank_em")
            return items[:top_n]
        except Exception as e:
            logger.warning(f"获取热门榜单失败: {e}")
            return []

    def get_limit_up_pool(
        self,
        date: Optional[str] = None,
    ) -> list[HotStockItem]:
        """获取涨停板池。"""
        try:
            if date:
                df = ak.stock_zt_pool_em(date=date)
            else:
                today = datetime.now().strftime("%Y%m%d")
                df = ak.stock_zt_pool_em(date=today)
            return _zt_pool_to_items(df, "stock_zt_pool_em")
        except Exception as e:
            logger.warning(f"获取涨停池失败: {e}")
            return []
