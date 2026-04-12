from typing import Literal, Optional
from pydantic import BaseModel
from .evidence import Citation


class EvaluationResult(BaseModel):
    confidence: Literal["low", "medium", "high"]
    evidence_coverage: Literal["insufficient", "partial", "good"]
    conclusion_stability: Literal["fragile", "moderate", "stable"]
    major_gaps: list[str] = []
    warnings: list[str] = []
    factual_evidence_ids: list[str] = []
    inferred_evidence_ids: list[str] = []


class OpinionCard(BaseModel):
    symbol: str
    company_name: str
    stance_label: Literal["看多", "中性", "看空"]
    confidence_label: Literal["低", "中", "高"]
    one_liner: str
    current_price: Optional[float] = None
    expected_price_text: str
    horizon_text: str
    market_narrative: str
    core_drivers: list[str] = []
    key_risks: list[str] = []
    watch_points: list[str] = []
    generated_at: str


class EvidenceChainItem(BaseModel):
    title: str
    interpretation: str
    direction: Literal["support", "oppose", "mixed"]
    citation: Optional[Citation] = None


class InformationChangeItem(BaseModel):
    time: str
    change: str
    implication: str


class ExpandedOpinionCard(OpinionCard):
    debate_points: list[str] = []
    evidence_chain: list[EvidenceChainItem] = []
    information_changes: list[InformationChangeItem] = []
    anchor_summary: str = ""
