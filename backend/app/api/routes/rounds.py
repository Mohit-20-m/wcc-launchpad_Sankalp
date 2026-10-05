"""Rounds: what teams may submit, when, who may enter, and the
organizer's controls over the clock (close early, extend, per-team
extensions, advancement). Mounted under /events/{event_id}/rounds."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_event_or_404, get_owned_event
from app.core.security import require_role
from app.models.judging import Score
from app.models.project import Project
from app.models.round import Round, RoundAdvancement, TeamExtension
from app.models.team import Team
from app.models.user import User, UserRole
from app.schemas.rounds import (
    AdvanceRequest,
    AdvanceTopRequest,
    ExtendRequest,
    ExtendTeamRequest,
    RoundCreate,
    RoundOut,
    RoundUpdate,
)
from app.services.announce import announce
from app.services.audit import audit
from app.services.live import hub
from app.services.results import compute_results
from app.services.rounds import aware, get_rounds, now_utc, round_state, sync_event_deadline

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))


async def _round(db: AsyncSession, event_id: str, round_id: str) -> Round:
    rnd = (
        await db.execute(select(Round).where(Round.id == round_id, Round.event_id == event_id))
    ).scalar_one_or_none()
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found.")
    return rnd


async def _scores_in_round(db: AsyncSession, round_id: str) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(Score).join(Project, Project.id == Score.project_id).where(Project.round_id == round_id)
        )
    ) or 0


def _fmt(dt: datetime) -> str:
    return aware(dt).strftime("%d %b %Y, %H:%M UTC")


@router.get("", response_model=list[RoundOut])
async def list_rounds(event_id: str, db: AsyncSession = Depends(get_db)):
    await get_event_or_404(db, event_id)
    return [RoundOut.model_validate(r) for r in await get_rounds(db, event_id)]


@router.post("", response_model=RoundOut, status_code=status.HTTP_201_CREATED)
async def add_round(event_id: str, payload: RoundCreate, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    rounds = await get_rounds(db, event_id)
    if rounds and payload.closes_at <= aware(rounds[-1].closes_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A new round must close after the previous round.")
    rnd = Round(
        event_id=event_id, number=(rounds[-1].number + 1) if rounds else 1, name=payload.name,
        instructions=payload.instructions, opens_at=payload.opens_at, closes_at=payload.closes_at,
        allow_idea=payload.allow_idea, allow_repo=payload.allow_repo, allow_video=payload.allow_video,
        allow_files=payload.allow_files, file_types=",".join(payload.file_types), max_file_mb=payload.max_file_mb,
        open_to_all=payload.open_to_all if rounds else True,
    )
    db.add(rnd)
    await db.flush()
    await sync_event_deadline(db, event)
    await audit(db, "round.create", event_id=event_id, actor=organizer, target_type="round", target_id=rnd.id,
                detail={"number": rnd.number, "name": rnd.name})
    await db.commit()
    await db.refresh(rnd)
    await hub.publish(event_id, "rounds")
    return RoundOut.model_validate(rnd)


@router.patch("/{round_id}", response_model=RoundOut)
async def update_round(event_id: str, round_id: str, payload: RoundUpdate, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    changes = payload.model_dump(exclude_unset=True)
    if "file_types" in changes and changes["file_types"] is not None:
        changes["file_types"] = ",".join(changes["file_types"])
    if rnd.number == 1:
        changes.pop("open_to_all", None)  # round 1 is always open to everyone
    for k, v in changes.items():
        if v is None and k not in ("instructions", "opens_at"):
            continue
        setattr(rnd, k, v)
    if rnd.opens_at and aware(rnd.opens_at) >= aware(rnd.closes_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A round must close after it opens.")
    await audit(db, "round.update", event_id=event_id, actor=organizer, target_type="round", target_id=rnd.id,
                detail={k: v for k, v in changes.items()})
    await db.commit()
    await db.refresh(rnd)
    await hub.publish(event_id, "rounds")
    return RoundOut.model_validate(rnd)


@router.delete("/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_round(event_id: str, round_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    rounds = await get_rounds(db, event_id)
    rnd = await _round(db, event_id, round_id)
    if len(rounds) == 1 or rounds[-1].id != rnd.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only the last round can be removed, and an event needs at least one round.")
    has_work = await db.scalar(select(func.count()).select_from(Project).where(Project.round_id == rnd.id))
    if has_work:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This round already has submissions and can't be removed.")
    for model in (RoundAdvancement, TeamExtension):
        for row in (await db.execute(select(model).where(model.round_id == rnd.id))).scalars().all():
            await db.delete(row)
    await db.delete(rnd)
    await db.flush()
    await sync_event_deadline(db, event)
    await audit(db, "round.delete", event_id=event_id, actor=organizer, target_type="round", target_id=round_id)
    await db.commit()
    await hub.publish(event_id, "rounds")


@router.post("/{round_id}/close-submissions", response_model=RoundOut)
async def close_submissions(event_id: str, round_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """Stop accepting submissions now, before the deadline, so judges can
    start scoring. Cancels any per-team extensions for this round."""
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    active_extensions = (
        await db.execute(select(TeamExtension).where(TeamExtension.round_id == rnd.id, TeamExtension.closes_at > now_utc()))
    ).scalars().all()
    if round_state(rnd) == "closed" and not active_extensions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Submissions for this round are already closed.")
    # (A round past its deadline can still be open for a team holding an
    # extension; closing then ends that extra time too.)
    rnd.closed_early_at = now_utc()
    rnd.closed_notified_at = now_utc()  # the audit row below is what fires round.closed
    cancelled = 0
    for ext in (await db.execute(select(TeamExtension).where(TeamExtension.round_id == rnd.id))).scalars().all():
        await db.delete(ext)
        cancelled += 1
    await audit(db, "round.close_early", event_id=event_id, actor=organizer, target_type="round", target_id=rnd.id,
                detail={"round": rnd.number, "team_extensions_cancelled": cancelled})
    await announce(db, event_id, organizer, f"Submissions for {rnd.name} are now closed. Judging can begin.")
    await db.commit()
    await db.refresh(rnd)
    await hub.publish(event_id, "rounds", "announcements", "stats", "submissions")
    return RoundOut.model_validate(rnd)


@router.post("/{round_id}/extend", response_model=RoundOut)
async def extend_round(event_id: str, round_id: str, payload: ExtendRequest, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """Move the round's deadline (also reopens a round that was closed,
    early or on time)."""
    event = await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    now = now_utc()
    if aware(payload.closes_at) <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The new deadline must be in the future.")
    if round_state(rnd) == "open" and aware(payload.closes_at) <= aware(rnd.closes_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An extension must move the deadline later. To end submissions sooner, use Close submissions.")
    old, was_closed_early = rnd.closes_at, rnd.closed_early_at is not None
    scored = await _scores_in_round(db, rnd.id)
    rnd.closes_at = payload.closes_at
    rnd.closed_early_at = None
    rnd.closed_notified_at = None  # it can close (and notify) again later
    await sync_event_deadline(db, event)
    await audit(db, "round.extend", event_id=event_id, actor=organizer, target_type="round", target_id=rnd.id,
                detail={"round": rnd.number, "from": old, "to": payload.closes_at, "reason": payload.reason,
                        "was_closed_early": was_closed_early, "scores_already_recorded": scored})
    await announce(db, event_id, organizer,
                   f"{rnd.name} deadline moved to {_fmt(payload.closes_at)}." + (f" {payload.reason}" if payload.reason else ""))
    await db.commit()
    await db.refresh(rnd)
    await hub.publish(event_id, "rounds", "announcements", "stats", "submissions")
    return RoundOut.model_validate(rnd)


class ExtensionOut(BaseModel):
    team_id: str
    team_name: str
    closes_at: datetime
    reason: str | None = None


@router.get("/{round_id}/extensions", response_model=list[ExtensionOut])
async def list_extensions(event_id: str, round_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    rows = (
        await db.execute(
            select(TeamExtension, Team.name).join(Team, Team.id == TeamExtension.team_id).where(TeamExtension.round_id == rnd.id)
        )
    ).all()
    return [ExtensionOut(team_id=e.team_id, team_name=n, closes_at=e.closes_at, reason=e.reason) for e, n in rows]


@router.post("/{round_id}/extend-team", response_model=ExtensionOut)
async def extend_for_team(event_id: str, round_id: str, payload: ExtendTeamRequest, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """Give ONE team extra time on this round, without reopening it for
    everyone else."""
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    team = (await db.execute(select(Team).where(Team.id == payload.team_id, Team.event_id == event_id))).scalar_one_or_none()
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That team isn't part of this event.")
    if rnd.closed_early_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This round was closed early for everyone. Reopen it with an extension instead.")
    if aware(payload.closes_at) <= now_utc():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The new deadline must be in the future.")
    if aware(payload.closes_at) <= aware(rnd.closes_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A team extension must be later than the round's own deadline.")
    ext = (await db.execute(select(TeamExtension).where(TeamExtension.round_id == rnd.id, TeamExtension.team_id == team.id))).scalar_one_or_none()
    if ext is None:
        ext = TeamExtension(round_id=rnd.id, team_id=team.id, closes_at=payload.closes_at, reason=payload.reason, granted_by=organizer.id)
        db.add(ext)
    else:
        ext.closes_at, ext.reason, ext.granted_by = payload.closes_at, payload.reason, organizer.id
    await audit(db, "round.extend_team", event_id=event_id, actor=organizer, target_type="team", target_id=team.id,
                detail={"round": rnd.number, "team": team.name, "to": payload.closes_at, "reason": payload.reason})
    await db.commit()
    await hub.publish(event_id, "rounds")
    return ExtensionOut(team_id=team.id, team_name=team.name, closes_at=ext.closes_at, reason=ext.reason)


@router.delete("/{round_id}/extend-team/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_team_extension(event_id: str, round_id: str, team_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    ext = (await db.execute(select(TeamExtension).where(TeamExtension.round_id == rnd.id, TeamExtension.team_id == team_id))).scalar_one_or_none()
    if ext is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No extension for that team.")
    await db.delete(ext)
    await audit(db, "round.extension_revoked", event_id=event_id, actor=organizer, target_type="team", target_id=team_id, detail={"round": rnd.number})
    await db.commit()
    await hub.publish(event_id, "rounds")


# ------------------------------ advancement ------------------------------

class AdvancedOut(BaseModel):
    team_id: str
    team_name: str


async def _target_round(db: AsyncSession, event_id: str, round_id: str) -> tuple[Round, Round]:
    rnd = await _round(db, event_id, round_id)
    if rnd.number == 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Round 1 is open to everyone; teams are advanced into later rounds.")
    prev = next((r for r in await get_rounds(db, event_id) if r.number == rnd.number - 1), None)
    if prev is None or round_state(prev) != "closed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Close the previous round's submissions before advancing teams.")
    return rnd, prev


@router.get("/{round_id}/advanced", response_model=list[AdvancedOut])
async def list_advanced(event_id: str, round_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    rows = (
        await db.execute(
            select(Team.id, Team.name).join(RoundAdvancement, RoundAdvancement.team_id == Team.id).where(RoundAdvancement.round_id == rnd.id).order_by(Team.name)
        )
    ).all()
    return [AdvancedOut(team_id=i, team_name=n) for i, n in rows]


async def _advance(db: AsyncSession, event_id: str, rnd: Round, team_ids: list[str], organizer: User, how: str) -> list[AdvancedOut]:
    teams = (await db.execute(select(Team).where(Team.id.in_(team_ids), Team.event_id == event_id))).scalars().all()
    if len(teams) != len(set(team_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One of those teams isn't part of this event.")
    have = {r[0] for r in (await db.execute(select(RoundAdvancement.team_id).where(RoundAdvancement.round_id == rnd.id))).all()}
    for t in teams:
        if t.id not in have:
            db.add(RoundAdvancement(round_id=rnd.id, team_id=t.id))
    await audit(db, "round.advance", event_id=event_id, actor=organizer, target_type="round", target_id=rnd.id,
                detail={"into": rnd.number, "how": how, "teams": [t.name for t in teams]})
    await announce(db, event_id, organizer, f"{len(teams)} team(s) advanced to {rnd.name}. Check your squad page.")
    await db.commit()
    await hub.publish(event_id, "rounds", "announcements", "teams")
    return [AdvancedOut(team_id=t.id, team_name=t.name) for t in teams]


@router.post("/{round_id}/advance", response_model=list[AdvancedOut])
async def advance_teams(event_id: str, round_id: str, payload: AdvanceRequest, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """Let the chosen teams into this round (organizer's pick)."""
    await get_owned_event(db, event_id, organizer)
    rnd, _prev = await _target_round(db, event_id, round_id)
    return await _advance(db, event_id, rnd, payload.team_ids, organizer, "manual")


@router.post("/{round_id}/advance-top", response_model=list[AdvancedOut])
async def advance_top(event_id: str, round_id: str, payload: AdvanceTopRequest, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """Advance the top N teams of the previous round, by normalized score."""
    await get_owned_event(db, event_id, organizer)
    rnd, prev = await _target_round(db, event_id, round_id)
    ranking = await compute_results(db, event_id, prev)
    if not ranking:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The previous round has no scored projects yet.")
    top_projects = [r["project_id"] for r in ranking[: payload.top_n]]
    team_ids = [
        row[0] for row in (await db.execute(select(Project.team_id).where(Project.id.in_(top_projects)))).all()
    ]
    return await _advance(db, event_id, rnd, list(dict.fromkeys(team_ids)), organizer, f"top {payload.top_n}")


@router.delete("/{round_id}/advance/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_advancement(event_id: str, round_id: str, team_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rnd = await _round(db, event_id, round_id)
    row = (await db.execute(select(RoundAdvancement).where(RoundAdvancement.round_id == rnd.id, RoundAdvancement.team_id == team_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That team wasn't advanced.")
    await db.delete(row)
    await audit(db, "round.advance_removed", event_id=event_id, actor=organizer, target_type="team", target_id=team_id, detail={"round": rnd.number})
    await db.commit()
    await hub.publish(event_id, "rounds", "teams")
