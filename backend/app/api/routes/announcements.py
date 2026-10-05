"""Organizer announcements -- the feed participants see. Reading is
public (it's event news); posting is organizer-only."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.announcement import Announcement
from app.models.event import Event
from app.models.user import User, UserRole
from app.schemas.announcements import AnnouncementCreate, AnnouncementOut
from app.services.audit import audit
from app.services.live import hub

router = APIRouter()


@router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
async def post_announcement(
    payload: AnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    if payload.event_id is None:
        # A global announcement reaches every event's participants, so
        # only an admin may post one. Organizers post to their own events.
        if organizer.role != UserRole.ADMIN:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose which of your events this announcement is for.")
    else:
        await get_owned_event(db, payload.event_id, organizer)  # 404 unknown, 403 not yours

    announcement = Announcement(event_id=payload.event_id, author_id=organizer.id, body=payload.body.strip())
    db.add(announcement)
    await db.flush()
    await audit(db, "announcement.post", event_id=payload.event_id, actor=organizer, target_type="announcement", target_id=announcement.id)
    await db.commit()
    await db.refresh(announcement)
    if payload.event_id:
        await hub.publish(payload.event_id, "announcements")
    return AnnouncementOut(
        id=announcement.id,
        event_id=announcement.event_id,
        body=announcement.body,
        author_name=organizer.name,
        created_at=announcement.created_at,
    )


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    event_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Announcement, User.name)
        .join(User, User.id == Announcement.author_id)
        .order_by(Announcement.created_at.desc())
        .limit(limit)
    )
    if event_id is not None:
        # An event's feed = its own announcements plus the global ones.
        stmt = stmt.where(or_(Announcement.event_id == event_id, Announcement.event_id.is_(None)))

    rows = (await db.execute(stmt)).all()
    return [
        AnnouncementOut(
            id=a.id,
            event_id=a.event_id,
            body=a.body,
            author_name=author_name,
            created_at=a.created_at,
        )
        for a, author_name in rows
    ]
