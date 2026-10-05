"""Data isolation between events: an organizer may only manage events
they own. Admins manage everything. Every organizer-facing event route
goes through `get_owned_event`, so isolation lives in one place."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import Event
from app.models.user import User, UserRole


async def get_event_or_404(db: AsyncSession, event_id: str, *, with_children: bool = False) -> Event:
    stmt = select(Event).where(Event.id == event_id)
    if with_children:
        stmt = stmt.options(selectinload(Event.tracks), selectinload(Event.prizes), selectinload(Event.rounds))
    event = (await db.execute(stmt)).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return event


def can_manage(event: Event, user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    return user.role == UserRole.ORGANIZER and event.owner_id == user.id


async def get_owned_event(db: AsyncSession, event_id: str, user: User, *, with_children: bool = False) -> Event:
    event = await get_event_or_404(db, event_id, with_children=with_children)
    if not can_manage(event, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage events you created.",
        )
    key_event = getattr(user, "api_key_event_id", None)
    if key_event is not None and key_event != event.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This API key belongs to a different event.")
    return event
