import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Closed events refuse submissions. Always enforced server-side,
    # against the server clock.
    submissions_close: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Optional scheduling/capacity fields the console's "Create an event"
    # form collects. Nullable so events created before they existed (and
    # the seeded fixture event) stay valid.
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Data isolation: an organizer manages only events they own (admins
    # manage all). See core/ownership.py.
    owner_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Set when the organizer publishes: reveals judge rankings, winners and
    # community-vote tallies to the public. Until then they are organizer-only.
    results_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    results_round_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # The audit chain position at the moment results were published.
    results_anchor_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    results_anchor_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # --- Community voting configuration ---
    # off | authenticated | email_gated | open_link
    voting_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="off")
    # single (one vote per project, up to voting_max_votes projects)
    # | quadratic (n votes on a project cost n^2 of voting_credits)
    voting_method: Mapped[str] = mapped_column(String(20), nullable=False, default="single")
    voting_opens_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_closes_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_max_votes: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    voting_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Plain string (no FK) on purpose: avoids a circular events<->rounds FK.
    voting_round_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    rounds: Mapped[list["Round"]] = relationship(order_by="Round.number", cascade="all, delete-orphan")
    tracks: Mapped[list["Track"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    prizes: Mapped[list["Prize"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    event: Mapped["Event"] = relationship(back_populates="tracks")


class Prize(Base):
    __tablename__ = "prizes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    event: Mapped["Event"] = relationship(back_populates="prizes")
