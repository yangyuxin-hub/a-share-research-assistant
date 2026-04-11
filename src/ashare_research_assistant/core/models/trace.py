from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


SessionStage = Literal[
    "observing",
    "routing",
    "clarifying",
    "researching",
    "searching",
    "evaluating",
    "synthesizing",
    "completed",
    "degraded",
]

TraceActor = Literal[
    "router",
    "orchestrator",
    "search_agent",
    "research_agent",
    "hotlist_agent",
    "synthesis_agent",
    "evaluator",
]


class TraceEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    turn_id: str
    stage: SessionStage
    actor: TraceActor
    action: str
    summary: str
    input_ref: Optional[str] = None
    output_ref: Optional[str] = None
    rationale: Optional[str] = None
    created_at: str
