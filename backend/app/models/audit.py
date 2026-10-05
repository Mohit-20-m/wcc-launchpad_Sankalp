import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """
    Append-only record of organizer actions and integrity-relevant events
    (deadline changes, assignments, ballots, rate-limit hits, publishing).
    Readable by the event's organizer in the UI and as CSV -- no database
    client needed. Nothing in the app updates or deletes these rows.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (UniqueConstraint("event_key", "seq", name="uq_audit_chain"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("events.id"), nullable=True, index=True)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Tamper-evidence: each row commits to the one before it (per event).
    event_key: Mapped[str] = mapped_column(String(36), nullable=False, default="_global", index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
