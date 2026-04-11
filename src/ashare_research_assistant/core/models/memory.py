from typing import Literal, Optional
from pydantic import BaseModel


class UserMemoryProfile(BaseModel):
    user_id: str = "default"
    style_preference: Optional[str] = None
    risk_preference: Optional[Literal["aggressive", "balanced", "conservative"]] = None
    preferred_frameworks: list[str] = []
    watchlist_symbols: list[str] = []
    favorite_themes: list[str] = []
    disliked_patterns: list[str] = []
    output_preference: Optional[Literal["brief_first", "evidence_first", "balanced"]] = None
    long_term_hypotheses: list[str] = []
    updated_at: str


class WorkingMemory(BaseModel):
    active_task: Optional[str] = None
    confirmed_constraints: list[str] = []
    recent_symbols: list[str] = []
    recent_topics: list[str] = []
    open_questions: list[str] = []
    provisional_conclusions: list[str] = []
    memory_version: int = 0
