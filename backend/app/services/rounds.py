"""Round logic in one place: is a round open, closed, or not open yet --
for a given team, since one team may hold an extension the others lack."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.project import Project
from app.models.round import Round, TeamExtension


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def round_state(rnd: Round, ext_closes_at: Optional[datetime] = None, now: Optional[datetime] = None) -> str:
    """'not_open' | 'open' | 'closed'.

    Scoring is allowed only when a round is 'closed'; submitting and
    editing only when it is 'open'. An early close by the organizer wins
    over everything (it also removes per-team extensions)."""
    now = now or now_utc()
    if rnd.closed_early_at is not None:
        return "closed"
    if rnd.opens_at is not None and now < aware(rnd.opens_at):
        return "not_open"
    if ext_closes_at is not None and aware(ext_closes_at) > now:
        return "open"
    if now >= aware(rnd.closes_at):
        return "closed"
    return "open"


async def get_rounds(db: AsyncSession, event_id: str) -> list[Round]:
    result = await db.execute(select(Round).where(Round.event_id == event_id).order_by(Round.number))
    return list(result.scalars().all())


async def ensure_default_round(db: AsyncSession, event: Event) -> Round:
    """Every event has at least one round; an event created without any
    gets an implicit Round 1 that allows everything."""
    rounds = await get_rounds(db, event.id)
    if rounds:
        return rounds[0]
    rnd = Round(event_id=event.id, number=1, name="Round 1", closes_at=event.submissions_close)
    db.add(rnd)
    await db.flush()
    return rnd


async def sync_event_deadline(db: AsyncSession, event: Event) -> None:
    """Event.submissions_close mirrors the LAST round's deadline, so older
    code (and the fixtures' "already closed" event) keeps its meaning."""
    latest = (
        await db.execute(select(func.max(Round.closes_at)).where(Round.event_id == event.id))
    ).scalar_one_or_none()
    if latest is not None:
        event.submissions_close = latest


async def get_extension(db: AsyncSession, round_id: str, team_id: str) -> Optional[TeamExtension]:
    return (
        await db.execute(
            select(TeamExtension).where(TeamExtension.round_id == round_id, TeamExtension.team_id == team_id)
        )
    ).scalar_one_or_none()


async def team_round_state(db: AsyncSession, rnd: Round, team_id: str) -> str:
    ext = await get_extension(db, rnd.id, team_id)
    return round_state(rnd, ext.closes_at if ext else None)


async def project_round(db: AsyncSession, project: Project) -> Optional[Round]:
    if project.round_id:
        return (await db.execute(select(Round).where(Round.id == project.round_id))).scalar_one_or_none()
    return None
