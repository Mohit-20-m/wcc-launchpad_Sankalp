import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DEFAULT_FILE_TYPES = "pdf,ppt,pptx,png,jpg,jpeg,zip,md,txt"


class Round(Base):
    """
    One stage of an event (Round 1: ideas, Round 2: slides + repo, ...).
    The organizer states what teams may submit in each round; the server
    rejects any field the round does not allow. Every event has at least
    one round (an event created without rounds gets an implicit Round 1
    that allows everything), so the rest of the code never special-cases
    "no rounds".
    """

    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("event_id", "number", name="uq_round_event_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    opens_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The organizer stopped submissions before the deadline so judges can
    # start scoring. Extending the round clears this.
    closed_early_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the round.closed webhook was queued (so a deadline passing fires it once).
    closed_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # What a team may submit in this round.
    allow_idea: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # summary + tech stack
    allow_repo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_files: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    file_types: Mapped[str] = mapped_column(String(200), nullable=False, default=DEFAULT_FILE_TYPES)
    max_file_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=25)

    # False: only teams the organizer advanced into this round may submit.
    open_to_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RoundAdvancement(Base):
    """A team the organizer let into a (later) round."""

    __tablename__ = "round_advancements"
    __table_args__ = (UniqueConstraint("round_id", "team_id", name="uq_advancement_round_team"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    round_id: Mapped[str] = mapped_column(String(36), ForeignKey("rounds.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TeamExtension(Base):
    """A deadline extension granted to ONE team for ONE round."""

    __tablename__ = "team_extensions"
    __table_args__ = (UniqueConstraint("round_id", "team_id", name="uq_extension_round_team"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    round_id: Mapped[str] = mapped_column(String(36), ForeignKey("rounds.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    granted_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
