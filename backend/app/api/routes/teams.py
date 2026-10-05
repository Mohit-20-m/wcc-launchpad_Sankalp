from typing import Optional

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.event import Event
from app.models.project import Project
from app.models.team import Team, TeamMember
from app.models.user import User
from app.schemas.projects import ProjectOut
from app.models.round import Round
from app.schemas.teams import TeamCreate, TeamJoin, TeamMemberOut, TeamMineOut, TeamOut, TeamRoundStatus
from app.services.audit import audit
from app.services.live import hub
from app.services.rounds import get_extension, get_rounds, round_state
from app.services.submissions import pick_round, project_out, team_can_enter

router = APIRouter()

MAX_TEAM_SIZE = 4  # teams of one to four people


async def _already_in_team_for_event(db: AsyncSession, user_id: str, event_id: str) -> bool:
    return (
        await db.execute(
            select(TeamMember.id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id == user_id, Team.event_id == event_id)
        )
    ).first() is not None


def _generate_invite_code() -> str:
    return secrets.token_urlsafe(6)


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = await db.execute(select(Event).where(Event.id == payload.event_id))
    if event.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")

    if await _already_in_team_for_event(db, current_user.id, payload.event_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You're already on a team for this event. Leave it before starting another.")

    team = Team(event_id=payload.event_id, name=payload.name, invite_code=_generate_invite_code())
    db.add(team)
    await db.flush()

    db.add(TeamMember(team_id=team.id, user_id=current_user.id, is_leader=True))
    await audit(db, "team.create", event_id=payload.event_id, actor=current_user, target_type="team", target_id=team.id,
                detail={"name": team.name})
    await db.commit()
    await db.refresh(team)
    await hub.publish(payload.event_id, "stats", "teams")
    return TeamOut.model_validate(team)


@router.post("/join", response_model=TeamOut)
async def join_team(
    payload: TeamJoin,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Team).where(Team.invite_code == payload.invite_code))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite code.")

    existing = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == current_user.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You're already on this team.")

    if await _already_in_team_for_event(db, current_user.id, team.event_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You're already on a team for this event.")
    size = len((await db.execute(select(TeamMember.id).where(TeamMember.team_id == team.id))).all())
    if size >= MAX_TEAM_SIZE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"This team is full (teams have at most {MAX_TEAM_SIZE} people).")

    db.add(TeamMember(team_id=team.id, user_id=current_user.id, is_leader=False))
    await audit(db, "team.join", event_id=team.event_id, actor=current_user, target_type="team", target_id=team.id)
    await db.commit()
    await hub.publish(team.event_id, "stats", "teams")
    return TeamOut.model_validate(team)


@router.get("/mine", response_model=list[TeamMineOut])
async def my_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's own teams, with members and their latest project.
    Members-only by construction: it only ever looks at teams the caller
    belongs to. NOTE: must stay declared above /{team_id}, otherwise
    "mine" would be captured as a team id."""
    team_ids = [
        row[0]
        for row in (
            await db.execute(select(TeamMember.team_id).where(TeamMember.user_id == current_user.id))
        ).all()
    ]
    if not team_ids:
        return []

    teams = (await db.execute(select(Team).where(Team.id.in_(team_ids)))).scalars().all()
    events = {
        e.id: e
        for e in (
            await db.execute(select(Event).where(Event.id.in_({t.event_id for t in teams})))
        ).scalars().all()
    }

    member_rows = (
        await db.execute(
            select(TeamMember, User.name)
            .join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id.in_(team_ids))
        )
    ).all()
    members_by_team: dict[str, list[TeamMemberOut]] = {}
    for member, name in member_rows:
        members_by_team.setdefault(member.team_id, []).append(
            TeamMemberOut(user_id=member.user_id, name=name, is_leader=member.is_leader)
        )

    projects = (await db.execute(select(Project).where(Project.team_id.in_(team_ids)))).scalars().all()
    by_team_round: dict[tuple[str, Optional[str]], Project] = {(p.team_id, p.round_id): p for p in projects}

    out: list[TeamMineOut] = []
    for team in teams:
        event = events.get(team.event_id)
        if event is None:
            continue
        members = sorted(members_by_team.get(team.id, []), key=lambda m: (not m.is_leader, m.name.lower()))
        rounds = await get_rounds(db, team.event_id)
        statuses: list[TeamRoundStatus] = []
        for r in rounds:
            ext = await get_extension(db, r.id, team.id)
            eligible = await team_can_enter(db, r, team.id)
            sub = by_team_round.get((team.id, r.id))
            effective_close = r.closes_at
            if ext is not None and ext.closes_at > r.closes_at:
                effective_close = ext.closes_at
            statuses.append(
                TeamRoundStatus(
                    round_id=r.id, number=r.number, name=r.name, instructions=r.instructions,
                    allow_idea=r.allow_idea, allow_repo=r.allow_repo, allow_video=r.allow_video,
                    allow_files=r.allow_files, file_types=r.file_types.split(","), max_file_mb=r.max_file_mb,
                    closes_at=effective_close, state=round_state(r, ext.closes_at if ext else None),
                    eligible=eligible, submission=await project_out(db, sub) if sub else None,
                )
            )
        current = await pick_round(db, team.event_id, team.id) if rounds else None
        current_status = next((x for x in statuses if current and x.round_id == current.id), None)
        out.append(
            TeamMineOut(
                id=team.id, name=team.name, invite_code=team.invite_code, event_id=team.event_id,
                event_name=event.name, submissions_close=event.submissions_close, members=members,
                project=current_status.submission if current_status else None,
                rounds=statuses, current_round_id=current.id if current else None,
            )
        )
    return out


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(team_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    return TeamOut.model_validate(team)
