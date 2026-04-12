from typing import Literal, Optional
from pydantic import BaseModel


class AnalysisWindow(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    horizon_label: Optional[Literal["1-3d", "1w", "2w", "1m", "custom"]] = None
    rationale: Optional[str] = None


class AnchorBasis(BaseModel):
    type: Literal[
        "event_repricing",
        "narrative_strength",
        "technical_resistance",
        "technical_support",
        "relative_strength",
        "volume_structure",
    ]
    description: str
    weight: Optional[float] = None


class PriceTarget(BaseModel):
    current_price: float
    expected_price_low: Optional[float] = None
    expected_price_high: Optional[float] = None
    target_label: str
    horizon: str
    stance: Literal["bullish", "neutral", "bearish"]
    anchor_basis: list[AnchorBasis] = []
    pricing_logic_summary: str
    upside_pct: Optional[float] = None
    downside_pct: Optional[float] = None
    generated_at: str


class StockResearchDraft(BaseModel):
    symbol: str
    company_name: str
    market_narrative: str
    thesis: str
    core_drivers: list[str] = []
    key_risks: list[str] = []
    debate_points: list[str] = []
    watch_points: list[str] = []
    supporting_evidence_ids: list[str] = []
    opposing_evidence_ids: list[str] = []
    unresolved_questions: list[str] = []
    price_target: PriceTarget
    stance: Literal["bullish", "neutral", "bearish"]
    reasoning_window: AnalysisWindow
