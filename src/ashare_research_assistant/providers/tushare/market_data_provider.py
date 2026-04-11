"""Tushare Pro 市场数据 Provider 实现。

Tushare Pro 文档：https://tushare.pro/document/2

无 Tushare Token 时，通过 akshare 搜索股票作为备用。
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import tushare as ts
import pandas as pd

from ashare_research_assistant.core.models import (
    DailyBar,
    DailyFactor,
    PriceSnapshot,
    SourceMeta,
    StockIdentifier,
    StockProfile,
)
from ashare_research_assistant.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)

_EXCHANGE_MAP = {
    "SSE": "SSE",
    "SZSE": "SZSE",
    "BSE": "BSE",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source(endpoint: str) -> SourceMeta:
    return SourceMeta(
        provider="tushare",
        endpoint=endpoint,
        fetched_at=_now_iso(),
        reliability="licensed",
    )


class TushareMarketDataProvider(MarketDataProvider):
    def __init__(self, token: str | None = None) -> None:
        if not token:
            logger.warning("Tushare token 未配置，市场数据将使用 akshare/cninfo")
            self._token: str | None = None
            self._pro = None
            self._stock_list = pd.DataFrame()
            self._akshare_cache: pd.DataFrame = pd.DataFrame()  # 延迟加载
            return
        ts.set_token(token)
        self._pro = ts.pro_api()
        self._token = token
        # 加载股票基础列表（用于名称→代码解析）
        self._stock_list: pd.DataFrame = self._load_stock_list()
        self._akshare_cache: pd.DataFrame = pd.DataFrame()

    def _ensure_initialized(self) -> None:
        """延迟初始化，在 token 后续配置时调用"""
        if self._pro is None and self._token:
            ts.set_token(self._token)
            self._pro = ts.pro_api()
            self._stock_list = self._load_stock_list()

    def _load_stock_list(self) -> pd.DataFrame:
        if self._pro is None:
            return pd.DataFrame()
        try:
            df = self._pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,area,industry,market,list_date,exchange",
            )
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.warning(f"加载股票列表失败: {e}")
            return pd.DataFrame()

    def resolve_stock(self, query: str) -> list[StockIdentifier]:
        """通过代码或名称模糊匹配候选标的。"""
        if not self._stock_list.empty:
            return self._resolve_from_list(query)

        # 无 Tushare token 时，通过 akshare 搜索
        return self._resolve_via_akshare(query)

    def _resolve_from_list(self, query: str) -> list[StockIdentifier]:
        """从本地股票列表中查询（Tushare token 可用时）"""
        q = query.strip().upper()
        df = self._stock_list

        # 精确代码匹配（如 600519 或 600519.SH）
        exact = df[df["ts_code"].str.startswith(q) | df["symbol"].str.startswith(q)]
        if not exact.empty:
            return [self._row_to_identifier(r) for _, r in exact.head(5).iterrows()]

        # 名称模糊匹配
        name_match = df[df["name"].str.contains(query, na=False)]
        return [self._row_to_identifier(r) for _, r in name_match.head(5).iterrows()]

    def _resolve_via_akshare(self, query: str) -> list[StockIdentifier]:
        """通过 akshare 搜索股票（无需 Token）"""
        # 使用缓存避免重复请求
        if self._akshare_cache is None or self._akshare_cache.empty:
            self._akshare_cache = self._load_akshare_stock_list()
        df = self._akshare_cache

        # akshare 加载失败时使用硬编码的常用股票作为备用
        if df.empty:
            df = self._get_fallback_stocks()

        q = query.strip()
        # 代码精确匹配（支持 6 位代码）
        code_padded = q.zfill(6)
        code_exact = df[df["code"] == code_padded]
        if not code_exact.empty:
            return [self._akshare_row_to_identifier(r) for _, r in code_exact.head(5).iterrows()]

        # 名称模糊匹配
        name_match = df[df["name"].str.contains(q, na=False)]
        return [self._akshare_row_to_identifier(r) for _, r in name_match.head(5).iterrows()]

    def _get_fallback_stocks(self) -> pd.DataFrame:
        """备用股票列表（akshare 不可用时使用）"""
        import pandas as pd
        data = [
            ("600519", "贵州茅台"), ("000858", "五粮液"), ("600036", "招商银行"),
            ("601318", "中国平安"), ("000001", "平安银行"), ("000333", "美的集团"),
            ("300750", "宁德时代"), ("002475", "立讯精密"), ("000651", "格力电器"),
            ("600276", "恒瑞医药"), ("002594", "比亚迪"), ("600900", "长江电力"),
            ("601012", "隆基绿能"), ("600030", "中信证券"), ("601888", "中国中免"),
            ("002230", "科大讯飞"), ("300059", "东方财富"), ("688981", "中芯国际"),
            ("300015", "爱尔眼科"), ("000568", "泸州老窖"), ("600887", "伊利股份"),
            ("601398", "工商银行"), ("601939", "建设银行"), ("600000", "浦发银行"),
            ("000537", "绿发电力"), ("000539", "粤电力A"), ("000543", "皖能电力"),
            ("000767", "晋控电力"), ("000966", "长源电力"), ("000690", "宝新能源"),
            ("001258", "立新能源"), ("600617", "国新能源"), ("001359", "平安电工"),
            ("000993", "闽东电力"), ("001289", "龙源电力"), ("002039", "黔源电力"),
        ]
        df = pd.DataFrame(data, columns=["code", "name"])
        return df

    def _load_akshare_stock_list(self) -> pd.DataFrame:
        """加载股票列表并缓存"""
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            if df is None or df.empty:
                logger.warning("akshare 返回空数据")
                return pd.DataFrame()
            df.columns = [c.strip() for c in df.columns]
            # 适配不同版本的 akshare 列名
            name_col = None
            code_col = None
            for col in df.columns:
                if 'name' in col.lower() and 'code' not in col.lower():
                    name_col = col
                if col.lower() == 'code' or 'symbol' in col.lower():
                    code_col = col
            if name_col is None or code_col is None:
                logger.warning(f"akshare 数据列名不匹配: {df.columns.tolist()}")
                return pd.DataFrame()
            # 重命名并统一格式
            df = df.rename(columns={code_col: "code", name_col: "name"})
            df["code"] = df["code"].astype(str).str.zfill(6)
            # 清理名称中的空格（如 "五 粮 液" -> "五粮液"）
            df["name"] = df["name"].astype(str).str.replace(" ", "", regex=False)
            logger.info(f"akshare 股票列表加载成功: {len(df)} 只")
            return df[["code", "name"]]
        except Exception as e:
            logger.warning(f"akshare 加载股票列表失败: {e}")
            return pd.DataFrame()

    def _akshare_row_to_identifier(self, row: pd.Series) -> StockIdentifier:
        symbol = str(row["code"])
        exchange = "SSE" if symbol.startswith(("6",)) else "SZSE" if symbol.startswith(("0", "3")) else "BSE" if symbol.startswith(("4", "8")) else "UNKNOWN"
        return StockIdentifier(symbol=symbol, name=str(row["name"]), exchange=exchange)

    def _row_to_identifier(self, row: pd.Series) -> StockIdentifier:
        exchange_raw = str(row.get("exchange", "")).upper()
        exchange = _EXCHANGE_MAP.get(exchange_raw, "UNKNOWN")
        return StockIdentifier(
            symbol=str(row["symbol"]),
            ts_code=str(row["ts_code"]),
            exchange=exchange,
            name=str(row["name"]),
            industry=str(row.get("industry", "")) or None,
        )

    def get_stock_profile(self, symbol: str) -> Optional[StockProfile]:
        ts_code = self._to_ts_code(symbol)
        if not ts_code:
            return None
        try:
            df = self._pro.stock_basic(
                ts_code=ts_code,
                fields="ts_code,symbol,name,area,industry,market,list_date,exchange",
            )
            if df is None or df.empty:
                return None
            row = df.iloc[0]
            identifier = self._row_to_identifier(row)
            return StockProfile(
                identifier=identifier,
                list_date=str(row.get("list_date", "")) or None,
                area=str(row.get("area", "")) or None,
                market=str(row.get("market", "")) or None,
                source=_source("stock_basic"),
            )
        except Exception as e:
            logger.error(f"get_stock_profile 失败 [{symbol}]: {e}")
            return None

    def get_price_snapshot(self, symbol: str) -> Optional[PriceSnapshot]:
        ts_code = self._to_ts_code(symbol)
        if not ts_code:
            return None
        try:
            df = self._pro.daily(
                ts_code=ts_code,
                fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
            )
            if df is None or df.empty:
                return None
            row = df.sort_values("trade_date", ascending=False).iloc[0]

            # 获取换手率等因子
            factors_df = self._pro.daily_basic(
                ts_code=ts_code,
                trade_date=str(row["trade_date"]),
                fields="turnover_rate,volume_ratio",
            )
            turnover_rate = None
            if factors_df is not None and not factors_df.empty:
                turnover_rate = float(factors_df.iloc[0].get("turnover_rate", 0) or 0) or None

            trade_date = str(row["trade_date"])
            return PriceSnapshot(
                symbol=symbol,
                trade_date=trade_date,
                current_price=float(row["close"]),
                prev_close=float(row["pre_close"]) if pd.notna(row.get("pre_close")) else None,
                change=float(row["change"]) if pd.notna(row.get("change")) else None,
                pct_change=float(row["pct_chg"]) if pd.notna(row.get("pct_chg")) else None,
                high=float(row["high"]) if pd.notna(row.get("high")) else None,
                low=float(row["low"]) if pd.notna(row.get("low")) else None,
                open=float(row["open"]) if pd.notna(row.get("open")) else None,
                volume=float(row["vol"]) if pd.notna(row.get("vol")) else None,
                amount=float(row["amount"]) if pd.notna(row.get("amount")) else None,
                turnover_rate=turnover_rate,
                data_timestamp=trade_date,
                source=_source("daily"),
            )
        except Exception as e:
            logger.error(f"get_price_snapshot 失败 [{symbol}]: {e}")
            return None

    def get_daily_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[DailyBar]:
        ts_code = self._to_ts_code(symbol)
        if not ts_code:
            return []
        try:
            df = self._pro.daily(
                ts_code=ts_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                fields="ts_code,trade_date,open,high,low,close,vol,amount,pct_chg",
            )
            if df is None or df.empty:
                return []
            bars = []
            for _, row in df.sort_values("trade_date").iterrows():
                bars.append(
                    DailyBar(
                        symbol=symbol,
                        trade_date=str(row["trade_date"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["vol"]) if pd.notna(row.get("vol")) else None,
                        amount=float(row["amount"]) if pd.notna(row.get("amount")) else None,
                        pct_change=float(row["pct_chg"]) if pd.notna(row.get("pct_chg")) else None,
                        source=_source("daily"),
                    )
                )
            return bars
        except Exception as e:
            logger.error(f"get_daily_bars 失败 [{symbol}]: {e}")
            return []

    def get_daily_factors(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> list[DailyFactor]:
        ts_code = self._to_ts_code(symbol)
        if not ts_code:
            return []
        try:
            df = self._pro.daily_basic(
                ts_code=ts_code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                fields="ts_code,trade_date,turnover_rate,volume_ratio,pe_ttm,pb,float_share,total_mv,circ_mv",
            )
            if df is None or df.empty:
                return []
            factors = []
            for _, row in df.sort_values("trade_date").iterrows():
                factors.append(
                    DailyFactor(
                        symbol=symbol,
                        trade_date=str(row["trade_date"]),
                        turnover_rate=float(row["turnover_rate"]) if pd.notna(row.get("turnover_rate")) else None,
                        volume_ratio=float(row["volume_ratio"]) if pd.notna(row.get("volume_ratio")) else None,
                        pe_ttm=float(row["pe_ttm"]) if pd.notna(row.get("pe_ttm")) else None,
                        pb=float(row["pb"]) if pd.notna(row.get("pb")) else None,
                        float_market_value=float(row["circ_mv"]) if pd.notna(row.get("circ_mv")) else None,
                        total_market_value=float(row["total_mv"]) if pd.notna(row.get("total_mv")) else None,
                        source=_source("daily_basic"),
                    )
                )
            return factors
        except Exception as e:
            logger.error(f"get_daily_factors 失败 [{symbol}]: {e}")
            return []

    def _to_ts_code(self, symbol: str) -> Optional[str]:
        """将股票代码转为 Tushare ts_code 格式（如 600519.SH）。"""
        symbol = symbol.strip().upper()
        # 已经是 ts_code 格式
        if "." in symbol:
            return symbol
        if self._stock_list.empty:
            # 根据规则推断
            return self._infer_ts_code(symbol)
        match = self._stock_list[self._stock_list["symbol"] == symbol]
        if not match.empty:
            return str(match.iloc[0]["ts_code"])
        return self._infer_ts_code(symbol)

    @staticmethod
    def _infer_ts_code(symbol: str) -> Optional[str]:
        """根据代码前缀推断交易所后缀。"""
        if not symbol.isdigit() or len(symbol) != 6:
            return None
        if symbol.startswith(("6",)):
            return f"{symbol}.SH"
        if symbol.startswith(("0", "3")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
        return None
