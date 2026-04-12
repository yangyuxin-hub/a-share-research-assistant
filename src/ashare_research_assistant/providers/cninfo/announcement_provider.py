"""巨潮资讯公告 Provider 实现。

使用 Tushare Pro 的公告接口作为主通道（tushare 接入巨潮数据），
并预留直连巨潮 API 的升级路径。

Tushare 公告接口文档：https://tushare.pro/document/2?doc_id=218
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import tushare as ts
import pandas as pd

from ashare_research_assistant.core.models import (
    AnnouncementDocument,
    AnnouncementItem,
    SourceMeta,
)
from ashare_research_assistant.providers.base import AnnouncementProvider

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source() -> SourceMeta:
    return SourceMeta(
        provider="cninfo_via_tushare",
        endpoint="anns",
        fetched_at=_now_iso(),
        reliability="official",
    )


class CninfoAnnouncementProvider(AnnouncementProvider):
    """
    第一版通过 Tushare Pro 的 anns 接口拉取公告列表。
    后续可替换为直连巨潮 OpenAPI。
    """

    def __init__(self, token: Optional[str] = None) -> None:
        if not token:
            logger.warning("CninfoProvider 未配置 Tushare token，公告功能将受限")
            self._pro = None
            return
        ts.set_token(token)
        self._pro = ts.pro_api()

    def search_announcements(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        keywords: Optional[list[str]] = None,
        max_results: int = 20,
    ) -> list[AnnouncementItem]:
        if self._pro is None:
            logger.warning("CninfoProvider 未初始化，无法搜索公告")
            return []

        ts_code = self._to_ts_code(symbol)
        if not ts_code:
            return []

        start = start_date.replace("-", "")
        end = end_date.replace("-", "")

        # 依次尝试已知的 Tushare 公告接口名
        _ANN_APIS = [
            ("stk_notices", "ts_code,ann_date,title,notice_type", "notice_type"),
            ("anns",        "ts_code,ann_date,title,ann_type",    "ann_type"),
            ("anns_d",      None,                                  None),
        ]
        df = None
        for api_name, fields_str, type_col in _ANN_APIS:
            try:
                api_fn = getattr(self._pro, api_name)
                kwargs: dict = {"ts_code": ts_code, "start_date": start, "end_date": end}
                if fields_str:
                    kwargs["fields"] = fields_str
                df = api_fn(**kwargs)
                if df is not None and not df.empty:
                    break
                df = None
            except Exception:
                df = None
                continue

        if df is None or df.empty:
            logger.warning(f"CninfoAnnouncementProvider: {symbol} 无公告数据（Tushare 接口不可用或无数据）")
            return []

        try:
            items = []
            date_col = "ann_date" if "ann_date" in df.columns else df.columns[0]
            cat_col = next((c for c in ("notice_type", "ann_type") if c in df.columns), None)
            for _, row in df.sort_values(date_col, ascending=False).head(max_results).iterrows():
                title = str(row.get("title", ""))
                if not title:
                    continue
                if keywords and not any(kw in title for kw in keywords):
                    continue
                items.append(AnnouncementItem(
                    id=f"{ts_code}_{row.get(date_col, '')}_{len(items)}",
                    symbol=symbol,
                    title=title,
                    publish_time=str(row.get(date_col, "")),
                    category=str(row.get(cat_col, "")) if cat_col else None,
                    source=_source(),
                ))
            return items
        except Exception as e:
            logger.warning(f"CninfoAnnouncementProvider.search_announcements 解析失败 [{symbol}]: {e}")
            return []

    def get_announcement_detail(self, announcement_id: str) -> Optional[AnnouncementDocument]:
        # 第一版暂不实现全文解析，仅返回列表级信息
        logger.info(f"get_announcement_detail 暂未实现全文解析: {announcement_id}")
        return None

    @staticmethod
    def _to_ts_code(symbol: str) -> Optional[str]:
        symbol = symbol.strip().upper()
        if "." in symbol:
            return symbol
        if not symbol.isdigit() or len(symbol) != 6:
            return None
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        if symbol.startswith(("0", "3")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
        return None
