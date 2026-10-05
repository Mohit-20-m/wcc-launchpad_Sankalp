"""The organizer's readable audit trail and conflict list -- no database
client needed. Event-scoped: an organizer only ever sees their own events'."""

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.audit import AuditLog
from app.models.judging import ConflictDeclaration, JudgeAssignment
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.extras import AuditOut
from app.schemas.judging import ConflictOut
from app.services.csvsafe import safe_cell

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))


@router.get("/events/{event_id}/audit", response_model=list[AuditOut])
async def read_audit(
    event_id: str,
    action: Optional[str] = Query(default=None, description="Exact action, or a prefix ending in '.' e.g. 'vote.'"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    organizer: User = Organizer,
):
    await get_owned_event(db, event_id, organizer)
    stmt = select(AuditLog).where(AuditLog.event_id == event_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%") if action.endswith(".") else AuditLog.action == action)
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return [AuditOut.model_validate(r) for r in rows]


@router.get("/events/{event_id}/audit.csv")
async def export_audit(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rows = (await db.execute(select(AuditLog).where(AuditLog.event_id == event_id).order_by(AuditLog.created_at))).scalars().all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time_utc", "actor", "action", "target_type", "target_id", "detail"])
    for r in rows:
        w.writerow([r.created_at.isoformat(), safe_cell(r.actor_label), r.action, r.target_type or "", r.target_id or "", safe_cell(r.detail or "")])
    out.seek(0)
    return StreamingResponse(out, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=audit_log.csv"})


@router.get("/events/{event_id}/conflicts", response_model=list[ConflictOut])
async def list_conflicts(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rows = (
        await db.execute(
            select(ConflictDeclaration, Project.title, User.name, User.email)
            .join(JudgeAssignment, (JudgeAssignment.judge_user_id == ConflictDeclaration.judge_user_id) & (JudgeAssignment.project_id == ConflictDeclaration.project_id))
            .join(Project, Project.id == ConflictDeclaration.project_id)
            .join(User, User.id == ConflictDeclaration.judge_user_id)
            .where(JudgeAssignment.event_id == event_id)
            .order_by(ConflictDeclaration.created_at.desc())
        )
    ).all()
    return [
        ConflictOut(project_id=c.project_id, judge_user_id=c.judge_user_id, project_title=title, judge_name=name, judge_email=email, reason=c.reason, created_at=c.created_at)
        for c, title, name, email in rows
    ]
