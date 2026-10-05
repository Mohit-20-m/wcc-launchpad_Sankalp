"""Tables for the Launchpad add-ons: email notifications, judge expertise
(for auto-assignment) and repository scans (for code-level duplicate
detection). New tables only -- nothing here alters an existing table, so
an existing database picks them up on the next start without a wipe."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return str(uuid.uuid4())


class EmailOutbox(Base):
    """One email. Written in the same transaction as the action that caused
    it (like webhook deliveries), then sent by the background dispatcher.
    `dedupe_key` makes sweeps idempotent: the same reminder is never queued
    twice for the same person."""

    __tablename__ = "email_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    # Rendered at send time (e.g. a certificate PDF), never stored as a blob.
    attachment_ref: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending", index=True)  # pending|sent|failed|skipped
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class MailSettings(Base):
    """Per-event switches. No row = defaults (everything on)."""

    __tablename__ = "mail_settings"
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reminder_hours: Mapped[str] = mapped_column(String(60), nullable=False, default="24,3")
    certificate_emails: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MailPreference(Base):
    """A user's own choice. Reminders and general updates can be switched
    off; emails a person needs to act on (team invites, certificates,
    judge assignments) always go out."""

    __tablename__ = "mail_preferences"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class JudgeExpertise(Base):
    """Tracks a judge knows well, per event. Used by auto-assignment."""

    __tablename__ = "judge_expertise"
    __table_args__ = (UniqueConstraint("event_id", "judge_user_id", "track_id", name="uq_judge_expertise"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=False, index=True)
    judge_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    track_id: Mapped[str] = mapped_column(String(36), ForeignKey("tracks.id"), nullable=False)


class RepoScan(Base):
    """The result of fetching one project's repository: code fingerprints
    for duplicate detection and the commit timeline."""

    __tablename__ = "repo_scans"
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    repo: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # owner/name
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")  # pending|done|skipped|error
    error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_fork: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fork_parent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    commit_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_commit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_commit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # {path: [fingerprint, ...]} -- never sent to the browser.
    fingerprints: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
