"""Integrity tools: verify the audit hash chain, publish a public anchor,
and surface duplicate/copied submissions."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_event_or_404, get_owned_event
from app.core.security import require_role
from app.models.audit import AuditLog
from app.models.project import Project, SubmissionStatus
from app.models.round import Round
from app.models.platform_layer import AuditHead
from app.models.team import Team
from app.models.user import User, UserRole
from app.services.audit import GENESIS, audit, compute_row_hash
from app.services.similarity import compare, find_pairs, make_item, prune_boilerplate

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))


async def verify_chain(db: AsyncSession, key: str, up_to: Optional[int] = None) -> dict:
    rows = (await db.execute(select(AuditLog).where(AuditLog.event_key == key).order_by(AuditLog.seq))).scalars().all()
    prev, expected, problem, bad, last_hash, checked = GENESIS, 1, None, None, GENESIS, 0
    for r in rows:
        if up_to is not None and r.seq > up_to:
            break
        if r.seq != expected:
            problem, bad = f"Entries are missing or reordered before #{expected}.", expected
            break
        if r.prev_hash != prev or compute_row_hash(prev, r.id, r.created_at, r.actor_label, r.action, r.target_type, r.target_id, r.detail, r.ip_hash) != r.row_hash:
            problem, bad = f"Entry #{r.seq} ({r.action}) was changed after it was written.", r.seq
            break
        prev = last_hash = r.row_hash
        expected, checked = r.seq + 1, checked + 1
    head = (await db.execute(select(AuditHead.seq, AuditHead.last_hash).where(AuditHead.event_key == key))).first()
    if problem is None and up_to is None and head and (head[0] != checked or head[1] != last_hash):
        problem, bad = "Entries were removed from the end of the log.", checked + 1
    return {"ok": problem is None, "checked": checked, "head_seq": head[0] if head else 0, "head_hash": head[1] if head else GENESIS,
            "problem": problem, "first_bad_seq": bad, "_last_hash": last_hash}


@router.get("/events/{event_id}/audit/verify")
async def audit_verify(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    res = await verify_chain(db, event_id)
    res.pop("_last_hash")
    return res


@router.get("/events/{event_id}/audit/anchor")
async def audit_anchor(event_id: str, db: AsyncSession = Depends(get_db)):
    """PUBLIC. The audit-chain position recorded when results were published,
    and whether the log up to that point still matches it. Reveals no content."""
    event = await get_event_or_404(db, event_id)
    if event.results_anchor_hash is None or event.results_published_at is None:
        return {"published": False, "anchor_seq": None, "anchor_hash": None, "verified": None}
    res = await verify_chain(db, event_id, up_to=event.results_anchor_seq)
    return {"published": True, "anchor_seq": event.results_anchor_seq, "anchor_hash": event.results_anchor_hash,
            "verified": bool(res["ok"] and res["checked"] == event.results_anchor_seq and res["_last_hash"] == event.results_anchor_hash),
            "published_at": event.results_published_at}


async def _items(db: AsyncSession, event_id: str, round_id: Optional[str] = None):
    stmt = (select(Project, Team.name, Round.number).join(Team, Team.id == Project.team_id).outerjoin(Round, Round.id == Project.round_id)
            .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT))
    if round_id:
        stmt = stmt.where(Project.round_id == round_id)
    return [make_item(p, tn, rn) for p, tn, rn in (await db.execute(stmt)).all()]


@router.get("/events/{event_id}/similarity")
async def similarity(event_id: str, round_id: Optional[str] = None, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    pairs = find_pairs(await _items(db, event_id, round_id))
    return {"pairs": pairs, "duplicate_entries": sum(p["kind"] == "duplicate_entry" for p in pairs), "possible_copies": sum(p["kind"] == "possible_copy" for p in pairs)}


async def flag_similar(db: AsyncSession, event_id: str, project_id: str) -> int:
    """Called after a submission: record (in the audit trail, hence webhooks)
    when it resembles another. Never blocks the submission."""
    items = prune_boilerplate(await _items(db, event_id))
    me = next((i for i in items if i.id == project_id), None)
    if me is None:
        return 0
    n = 0
    for other in items:
        if other.id == me.id:
            continue
        hit = compare(me, other)
        if hit:
            n += 1
            await audit(db, "submission.similar", event_id=event_id, actor_label="system", target_type="project", target_id=me.id,
                        detail={"other_project_id": other.id, "other_title": other.title, **hit})
            if n >= 3:
                break
    return n
