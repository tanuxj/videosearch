"""Request and response models for the search-history routes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HistoryClip(BaseModel):
    """One clip from a past search — an immutable snapshot of what the user saw."""

    id: str | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    frame: float = Field(ge=0)
    score: float = Field(ge=0, le=1)


class SearchHistoryIn(BaseModel):
    """A search the user just ran, to be remembered on the History page."""

    video_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=300)
    clips: list[HistoryClip] = Field(default_factory=list, max_length=50)
    expanded: bool = False
    min_score: float | None = Field(default=None, ge=0, le=1)


class SearchHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    prompt: str
    clips: list[HistoryClip]
    expanded: bool
    min_score: float | None
    created_at: datetime


class SearchHistoryListOut(BaseModel):
    items: list[SearchHistoryOut]
    count: int
