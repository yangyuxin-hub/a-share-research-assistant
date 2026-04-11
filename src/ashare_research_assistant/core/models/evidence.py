from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


class Citation(BaseModel):
    source_name: str
    url: Optional[str] = None
    document_id: Optional[str] = None
    published_at: Optional[str] = None


class EvidenceItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: Literal[
        "price",
        "factor",
        "announcement",
        "news",
        "company_profile",
        "hotspot",
        "inference",
        "risk_signal",
    ]
    title: str
    summary: str
    symbol: Optional[str] = None
    topic: Optional[str] = None
    event_time: Optional[str] = None
    support_direction: Optional[Literal["bullish", "neutral", "bearish", "mixed"]] = None
    strength: Optional[Literal["low", "medium", "high"]] = None
    factuality: Literal["fact", "derived", "inference"]
    citations: list[Citation] = []
    raw_ref: Optional[str] = None


class EvidenceBundle(BaseModel):
    symbol: Optional[str] = None
    query: Optional[str] = None
    items: list[EvidenceItem] = []
    gaps: list[str] = []
    contradictory_signals: list[str] = []
    last_updated_at: str
