"""SQLAlchemy ORM models for decks, cards, and review history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    decks: Mapped[list["Deck"]] = relationship(
        "Deck", back_populates="owner", cascade="all, delete-orphan"
    )


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    source_filename: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    source_pages: Mapped[Optional[int]] = mapped_column(Integer, default=None)
    # Background processing state: "processing" | "ready" | "failed"
    generation_status: Mapped[str] = mapped_column(String(20), default="ready")
    generation_error: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    owner: Mapped["User"] = relationship("User", back_populates="decks")
    cards: Mapped[list["Card"]] = relationship(
        "Card",
        back_populates="deck",
        cascade="all, delete-orphan",
        order_by="Card.id",
    )


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)

    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    card_type: Mapped[str] = mapped_column(String(30), default="qa")  # qa / cloze / definition
    source_excerpt: Mapped[Optional[str]] = mapped_column(Text, default=None)
    tags: Mapped[Optional[str]] = mapped_column(String(500), default=None)  # comma-separated

    # --- SM-2 state ---
    # ease factor (starts 2.5, min 1.3)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    # current interval in days
    interval_days: Mapped[float] = mapped_column(Float, default=0.0)
    # successful consecutive reviews
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    # count of times the card was forgotten (rated Again)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    # total number of reviews
    reviews_count: Mapped[int] = mapped_column(Integer, default=0)

    next_review: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_reviewed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # derived status: 'new' | 'learning' | 'review' | 'mastered'
    status: Mapped[str] = mapped_column(String(20), default="new")

    deck: Mapped["Deck"] = relationship("Deck", back_populates="cards")
    reviews: Mapped[list["ReviewLog"]] = relationship(
        "ReviewLog", back_populates="card", cascade="all, delete-orphan"
    )


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    quality: Mapped[int] = mapped_column(Integer)  # 0, 3, 4, 5 (Again, Hard, Good, Easy)
    interval_before: Mapped[float] = mapped_column(Float, default=0.0)
    interval_after: Mapped[float] = mapped_column(Float, default=0.0)
    ease_after: Mapped[float] = mapped_column(Float, default=2.5)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    card: Mapped["Card"] = relationship("Card", back_populates="reviews")
