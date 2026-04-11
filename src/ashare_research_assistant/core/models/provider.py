from typing import Literal, Optional
from pydantic import BaseModel


class SourceMeta(BaseModel):
    provider: str
    endpoint: Optional[str] = None
    fetched_at: str
    data_timestamp: Optional[str] = None
    reliability: Literal["official", "licensed", "aggregated", "scraped"]


class StockIdentifier(BaseModel):
    symbol: str
    ts_code: Optional[str] = None
    exchange: Optional[Literal["SSE", "SZSE", "BSE", "UNKNOWN"]] = None
    name: str
    aliases: list[str] = []
    industry: Optional[str] = None


class StockProfile(BaseModel):
    identifier: StockIdentifier
    list_date: Optional[str] = None
    area: Optional[str] = None
    market: Optional[str] = None
    concept_tags: list[str] = []
    business_summary: Optional[str] = None
    source: SourceMeta


class PriceSnapshot(BaseModel):
    symbol: str
    trade_date: str
    current_price: float
    prev_close: Optional[float] = None
    change: Optional[float] = None
    pct_change: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    amplitude: Optional[float] = None
    data_timestamp: str
    source: SourceMeta


class DailyBar(BaseModel):
    symbol: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    amount: Optional[float] = None
    pct_change: Optional[float] = None
    source: SourceMeta


class DailyFactor(BaseModel):
    symbol: str
    trade_date: str
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    float_market_value: Optional[float] = None
    total_market_value: Optional[float] = None
    source: SourceMeta


class AnnouncementItem(BaseModel):
    id: str
    symbol: str
    title: str
    publish_time: str
    category: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    exchange: Optional[str] = None
    source: SourceMeta


class AnnouncementDocument(BaseModel):
    id: str
    item: AnnouncementItem
    raw_text: Optional[str] = None
    extracted_summary: Optional[str] = None
    key_points: list[str] = []
    source: SourceMeta


class NewsItem(BaseModel):
    id: str
    title: str
    publish_time: str
    outlet: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    related_symbols: list[str] = []
    topic_tags: list[str] = []
    source: SourceMeta


class HotStockItem(BaseModel):
    symbol: str
    name: str
    heat_score: float
    momentum_score: Optional[float] = None
    event_score: Optional[float] = None
    narrative: Optional[str] = None
    reasons: list[str] = []
    related_themes: list[str] = []
    source: SourceMeta
