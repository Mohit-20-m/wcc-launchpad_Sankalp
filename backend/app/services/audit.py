"""The audit trail: append-only, hash-chained, and the source of webhook events.

TAMPER EVIDENCE. Every row stores `prev_hash` (the previous row's hash for
the same event) and `row_hash = SHA-256(prev_hash + the row's own fields)`.
Editing any past row, or deleting one, breaks every hash after it, and
`/events/{id}/audit/verify` recomputes the chain to prove it. The chain head
is also recorded when results are published, so the public can check that
the history behind published results was not rewritten afterwards.

The head is advanced with an atomic compare-and-swap UPDATE, so concurrent
requests (or several workers) can never fork the chain.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.platform_layer import AuditHead
from app.models.user import User

GENESIS = "0" * 64
GLOBAL_KEY = "_global"


def stamp(dt: datetime) -> str:
    """Canonical timestamp text (SQLite returns naive datetimes; treat as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def compute_row_hash(prev_hash: str, row_id: str, created: datetime, actor_label: str, action: str,
                     target_type: Optional[str], target_id: Optional[str], detail: Optional[str], ip_hash: Optional[str]) -> str:
    parts = [prev_hash, row_id, stamp(created), actor_label, action, target_type or "", target_id or "", detail or "", ip_hash or ""]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


async def audit(
    db: AsyncSession,
    action: str,
    *,
    event_id: Optional[str] = None,
    actor: Optional[User] = None,
    actor_label: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Any = None,
    ip_hash: Optional[str] = None,
) -> None:
    """Add a chained audit row to the caller's transaction (the caller
    commits, so the action and its audit record succeed or fail together),
    and queue any webhooks subscribed to this kind of action."""
    label = actor_label or (f"{actor.name} <{actor.email}>" if actor else "system")
    text = detail if isinstance(detail, str) or detail is None else json.dumps(detail, default=str)
    key = event_id or GLOBAL_KEY
    row_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc)

    for _ in range(12):
        head = (await db.execute(select(AuditHead.seq, AuditHead.last_hash).where(AuditHead.event_key == key))).first()
        if head is None:
            try:
                async with db.begin_nested():
                    db.add(AuditHead(event_key=key, seq=0, last_hash=GENESIS))
                    await db.flush()
            except IntegrityError:
                pass  # someone else created it first; re-read
            continue
        seq, prev = head
        row_hash = compute_row_hash(prev, row_id, created, label, action, target_type, target_id, text, ip_hash)
        swapped = await db.execute(
            update(AuditHead).where(AuditHead.event_key == key, AuditHead.seq == seq).values(seq=seq + 1, last_hash=row_hash)
        )
        if swapped.rowcount == 1:
            db.add(AuditLog(
                id=row_id, event_id=event_id, event_key=key, seq=seq + 1, prev_hash=prev, row_hash=row_hash,
                actor_user_id=actor.id if actor else None, actor_label=label, action=action,
                target_type=target_type, target_id=target_id, detail=text, ip_hash=ip_hash, created_at=created,
            ))
            break
    else:  # pragma: no cover
        raise RuntimeError("Could not advance the audit chain (too much contention).")

    if event_id:
        from app.services.webhooks import enqueue_for_action  # local: avoids an import cycle

        await enqueue_for_action(db, event_id, row_id, action, target_type, target_id, text, created)

        from app.services import mailer  # local: avoids an import cycle

        if action in mailer._HANDLERS:
            parsed = detail if isinstance(detail, dict) else None
            await mailer.enqueue_for_action(db, event_id, action, target_type, target_id, parsed, actor)
