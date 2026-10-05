"""Invite codes for the judge and organizer roles. Organizers can invite
judges; only admins can invite organizers; nobody can invite an admin."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.invite import RoleInvite
from app.models.user import User, UserRole
from app.schemas.extras import InviteCreate, InviteOut
from app.services.audit import audit

router = APIRouter()


def _out(i: RoleInvite) -> InviteOut:
    return InviteOut(
        id=i.id, code=i.code, role=i.role, label=i.label, event_id=i.event_id, max_uses=i.max_uses,
        used_count=i.used_count, expires_at=i.expires_at, revoked=i.revoked_at is not None, created_at=i.created_at,
    )


@router.post("", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    if payload.role not in (UserRole.JUDGE, UserRole.ORGANIZER):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invites are for the judge or organizer role.")
    if payload.role == UserRole.ORGANIZER and user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can invite organizers.")
    if payload.event_id:
        await get_owned_event(db, payload.event_id, user)

    invite = RoleInvite(
        code=secrets.token_urlsafe(9), role=payload.role, label=payload.label, created_by=user.id,
        event_id=payload.event_id, max_uses=payload.max_uses,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)) if payload.expires_in_days else None,
    )
    db.add(invite)
    await db.flush()
    await audit(db, "invite.create", event_id=payload.event_id, actor=user, target_type="invite", target_id=invite.id,
                detail={"role": payload.role.value, "max_uses": payload.max_uses})
    await db.commit()
    await db.refresh(invite)
    return _out(invite)


@router.get("", response_model=list[InviteOut])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    stmt = select(RoleInvite).order_by(RoleInvite.created_at.desc())
    if user.role != UserRole.ADMIN:
        stmt = stmt.where(RoleInvite.created_by == user.id)
    return [_out(i) for i in (await db.execute(stmt)).scalars().all()]


@router.delete("/{invite_id}", response_model=InviteOut)
async def revoke_invite(
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    invite = (await db.execute(select(RoleInvite).where(RoleInvite.id == invite_id))).scalar_one_or_none()
    if invite is None or (user.role != UserRole.ADMIN and invite.created_by != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found.")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(timezone.utc)
        await audit(db, "invite.revoke", event_id=invite.event_id, actor=user, target_type="invite", target_id=invite.id)
        await db.commit()
    return _out(invite)
