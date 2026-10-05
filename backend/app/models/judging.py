import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JudgingCriterion(Base):
    """
    An organizer-configured rubric entry for an event -- e.g.
    ("Functionality", weight=1.0). If an event has none configured,
    scoring falls back to treating all submitted criteria equally.
    """

    __tablename__ = "judging_criteria"
    __table_args__ = (UniqueConstraint("event_id", "name", name="uq_criterion_event_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=1.0)
    # Guidance shown to judges next to this criterion's slider.
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class JudgeAssignment(Base):
    """A judge assigned to review a specific project. Scoring an
    unassigned project is refused -- see routes/judging.py."""

    __tablename__ = "judge_assignments"
    __table_args__ = (UniqueConstraint("judge_user_id", "project_id", name="uq_assignment_judge_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    judge_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)


class Score(Base):
    """
    One judge's score for one project. `criteria` matches the shape
    fixtures.json uses: {"functionality": 4, "quality": 3, ...}.
    One row per (judge, project) -- resubmitting updates it in place.
    """

    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("judge_user_id", "project_id", name="uq_score_judge_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    judge_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PairwiseComparison(Base):
    """
    THE BONUS CHALLENGE: "Pairwise Mode" -- a Bradley-Terry estimator
    for pairwise judging comparison. An alternative to (not a
    replacement for) the 1-5 scoring above: a judge is shown two of
    their assigned projects and picks which is better, rather than
    inventing an absolute number. See services/bradley_terry.py for how
    a full ranking gets derived from many of these, and JUDGING.md for
    why this avoids the "what does a 4 even mean" problem that absolute
    scores have.
    """

    __tablename__ = "pairwise_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False)
    judge_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    project_a_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    project_b_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    winner_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ConflictDeclaration(Base):
    """A judge declared a conflict of interest on an assigned project
    (e.g. they know the team). They cannot score it; the organizer sees
    the declaration and can reassign."""

    __tablename__ = "conflict_declarations"
    __table_args__ = (UniqueConstraint("judge_user_id", "project_id", name="uq_conflict_judge_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    judge_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
