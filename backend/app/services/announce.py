from sqlalchemy.ext.asyncio import AsyncSession

from app.models.announcement import Announcement
from app.models.user import User


async def announce(db: AsyncSession, event_id: str, author: User, body: str) -> None:
    """Post to the participants' feed on the organizer's behalf, e.g.
    "Round 1 deadline extended". Added to the caller's transaction."""
    db.add(Announcement(event_id=event_id, author_id=author.id, body=body))
