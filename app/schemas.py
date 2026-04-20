"""Pydantic schemas (request/response DTOs)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CardOut(BaseModel):
    id: int
    deck_id: int
    front: str
    back: str
    card_type: str
    status: str
    interval_days: float
    ease_factor: float
    repetitions: int
    lapses: int
    reviews_count: int
    next_review: datetime
    last_reviewed: Optional[datetime]
    tags: Optional[str]
    source_excerpt: Optional[str]

    class Config:
        from_attributes = True


class DeckStats(BaseModel):
    total: int
    new: int
    learning: int
    review: int
    mastered: int
    due_now: int


class DeckOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    source_filename: Optional[str]
    source_pages: Optional[int]
    created_at: datetime
    updated_at: datetime
    stats: DeckStats

    class Config:
        from_attributes = True


class RateCardIn(BaseModel):
    rating: str = Field(..., pattern="^(again|hard|good|easy)$")


class RenameDeckIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)


class CardEditIn(BaseModel):
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
