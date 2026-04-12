from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid

from .provider import StockIdentifier
from .evidence import EvidenceBundle
from .clarification import ClarificationState
from .research import AnalysisWindow, StockResearchDraft
from .opinion import EvaluationResult, OpinionCard
from .trace import TraceEvent, SessionStage
from .memory import WorkingMemory, UserMemoryProfile


IntentType = Literal[
    "single_stock_analysis",
    "stock_compare_or_followup",
    "hot_candidate_discovery",
    "theme_or_topic_exploration",
    "general_market_question",
    "knowledge_question",     # 纯知识问题、问候、身份询问，直接回答
    "clarification_required",
]


class RouterResult(BaseModel):
    intent_type: IntentType
    resolved_entities: list[StockIdentifier] = []
    theme_keywords: list[str] = []  # 主题探索时的主题词
    confidence: float = 0.0
    clarification_needed: bool = False
    clarification_reason: Optional[str] = None


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_input: str = ""
    normalized_input: Optional[str] = None
    intent: Optional[IntentType] = None
    intent_confidence: Optional[float] = None
    stage: SessionStage = "observing"
    active_symbol: Optional[StockIdentifier] = None
    candidate_symbols: list[StockIdentifier] = []
    active_topic: Optional[str] = None
    analysis_window: Optional[AnalysisWindow] = None
    clarification: ClarificationState = Field(default_factory=ClarificationState)
    evidence_bundle: EvidenceBundle = Field(
        default_factory=lambda: EvidenceBundle(last_updated_at="")
    )
    research_draft: Optional[StockResearchDraft] = None
    evaluation: Optional[EvaluationResult] = None
    output_draft: Optional[OpinionCard] = None
    direct_answer: Optional[str] = None  # 纯知识问答的原始回复文本
    working_memory: WorkingMemory = Field(default_factory=WorkingMemory)
    user_memory_snapshot: Optional[UserMemoryProfile] = None
    trace: list[TraceEvent] = []
    created_at: str = ""
    updated_at: str = ""

    def new_turn(self, user_input: str) -> "SessionState":
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        return self.model_copy(
            update={
                "turn_id": str(uuid.uuid4()),
                "user_input": user_input,
                "stage": "observing",
                "updated_at": now,
            }
        )
