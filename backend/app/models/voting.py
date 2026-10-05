import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Vote(Base):
    """
    One voter's allocation to one project. A "ballot" is all of a voter's
    rows for an event. `voter_key` is derived from whatever identity the
    event's voting mode provides (see services/voting.py); it is a hash,
    never a raw email or token. The unique constraint is the hard
    duplicate-vote guarantee: it holds even if application code is wrong.
    """

    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("event_id", "voter_key", "project_id", name="uq_vote_voter_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    voter_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    voter_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # user | email | token
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    credits_spent: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class VoteAllowlist(Base):
    """Who may vote in an email-gated event: exact emails or '@domain'."""

    __tablename__ = "vote_allowlist"
    __table_args__ = (UniqueConstraint("event_id", "pattern", name="uq_allowlist_event_pattern"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    hidden_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)


class PrizeAward(Base):
    """Which project won which prize, recorded when results are published."""

    __tablename__ = "prize_awards"
    __table_args__ = (UniqueConstraint("event_id", "prize_id", name="uq_award_event_prize"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    prize_id: Mapped[str] = mapped_column(String(36), ForeignKey("prizes.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
