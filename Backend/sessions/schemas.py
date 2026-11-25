# sessions/schemas.py
# FIX: Python 3.9 needs List[X] instead of list[X]

from typing import List
from pydantic import BaseModel, AliasChoices, Field, field_validator
from agent.categories import normalize_category


class ActivityCategoryRequest(BaseModel):
    app_category: str = Field(default="unknown", validation_alias=AliasChoices("app_category", "active_window"))

    @field_validator("app_category", mode="before")
    @classmethod
    def sanitize_category(cls, value):
        return normalize_category(value)


class StuckRequest(ActivityCategoryRequest):
    session_id: str
    task_declared: str
    difficulty: str
    stuck_duration_minutes: int
    session_duration_minutes: int


class StuckSuggestion(BaseModel):
    strategy: str
    explanation: str
    first_step: str


class StuckResponse(BaseModel):
    suggestions: List[StuckSuggestion]
    encouragement: str
    session_id: str
