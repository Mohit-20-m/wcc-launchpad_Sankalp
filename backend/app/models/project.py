import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SubmissionStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    LOCKED = "locked"


class Project(Base):
    """
    NOTE ON SCHEMA: the original plan (see DATA-MODEL.md history) had a
    separate `submissions` table wrapping each project. We simplified to a
    single table with a `status` field directly on Project, matching the
    shape fixtures.json already uses (a project has one submitted_at, one
    lifecycle). This is a deliberate simplification for the 72-hour build,
    documented here and in DATA-MODEL.md rather than left unexplained.
    """

    __tablename__ = "projects"
    # One submission per team per round is enforced by the API (POST
    # replaces; see routes/projects.py), NOT by a database constraint:
    # fixtures.json deliberately contains a duplicate submission (prj_41
    # repeats team tm_07), and the platform must load it as-is.

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), nullable=False)
    round_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("rounds.id"), nullable=True)
    track_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tracks.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    repo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tech_stack: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[SubmissionStatus] = mapped_column(
        SAEnum(SubmissionStatus), nullable=False, default=SubmissionStatus.DRAFT
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    team: Mapped["Team"] = relationship()
    track: Mapped[Optional["Track"]] = relationship()


class ProjectFile(Base):
    """A file a team uploaded with a submission (slides, PDF, screenshots).
    The bytes live on disk under a random name (never the user's filename);
    they are only ever served through an authenticated endpoint."""

    __tablename__ = "project_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
