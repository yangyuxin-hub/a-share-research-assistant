from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


class ClarificationOption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    label: str
    description: str
    effect: str


class ClarificationQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    reason: Literal[
        "ambiguous_symbol",
        "unclear_goal",
        "missing_context",
        "too_many_candidates",
        "theme_selection",
    ]
    prompt: str
    help_text: Optional[str] = None
    options: list[ClarificationOption] = []
    allow_free_text: bool = True
    recommended_option_id: Optional[str] = None


class ClarificationState(BaseModel):
    status: Literal["idle", "pending", "answered", "skipped"] = "idle"
    question: Optional[ClarificationQuestion] = None
    answer_text: Optional[str] = None
    selected_option_id: Optional[str] = None
    asked_at: Optional[str] = None
    answered_at: Optional[str] = None
