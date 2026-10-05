from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.ownership import get_event_or_404, get_owned_event
from app.core.security import require_role
from app.models.event import Event, Prize, Track
from app.models.judging import (
    ConflictDeclaration,
    JudgeAssignment,
    JudgingCriterion,
    PairwiseComparison,
    Score,
)
from app.models.project import Project, SubmissionStatus
from app.models.round import Round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.schemas.events import EventCreate, EventOut, EventStats, SubmissionRow, TeamRow
from app.schemas.judging import CriterionCreate, CriterionOut, ProgressOut, ResultRow
from app.schemas.pairwise import PairwiseRankRow
from app.services.audit import audit
from app.services.bradley_terry import bradley_terry_strengths
from app.services.live import hub
from app.services.results import compute_results, resolve_round

router = APIRouter()

_EVENT_LOAD = (selectinload(Event.tracks), selectinload(Event.prizes), selectinload(Event.rounds))


async def _team_names(db: AsyncSession, project_ids: set[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    result = await db.execute(
        select(Project.id, Team.name).join(Team, Team.id == Project.team_id).where(Project.id.in_(project_ids))
    )
    return {pid: name for pid, name in result.all()}


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    closes = payload.submissions_close or payload.rounds[-1].closes_at
    event = Event(
        name=payload.name,
        description=payload.description,
        submissions_close=closes,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        capacity=payload.capacity,
        owner_id=organizer.id,
    )
    db.add(event)
    await db.flush()  # populate event.id before attaching children

    if payload.rounds:
        for i, r in enumerate(payload.rounds, start=1):
            db.add(
                Round(
                    event_id=event.id, number=i, name=r.name, instructions=r.instructions,
                    opens_at=r.opens_at, closes_at=r.closes_at,
                    allow_idea=r.allow_idea, allow_repo=r.allow_repo, allow_video=r.allow_video,
                    allow_files=r.allow_files, file_types=",".join(r.file_types), max_file_mb=r.max_file_mb,
                    open_to_all=True if i == 1 else r.open_to_all,  # round 1 is always open to everyone
                )
            )
    else:
        db.add(Round(event_id=event.id, number=1, name="Round 1", closes_at=closes))

    for t in payload.tracks:
        db.add(Track(event_id=event.id, name=t.name))
    for p in payload.prizes:
        db.add(Prize(event_id=event.id, name=p.name, amount=p.amount))

    await audit(db, "event.create", event_id=event.id, actor=organizer, target_type="event", target_id=event.id,
                detail={"name": event.name, "rounds": max(1, len(payload.rounds))})
    await db.commit()
    return EventOut.model_validate(await get_event_or_404(db, event.id, with_children=True))


@router.get("", response_model=list[EventOut])
async def list_events(db: AsyncSession = Depends(get_db)):
    # Public -- anyone browsing the platform should see what events exist.
    # Explicit order: without one, Postgres returns rows in no promised
    # order, and the consoles' default "first event" would be arbitrary.
    result = await db.execute(
        select(Event).options(*_EVENT_LOAD).order_by(Event.submissions_close, Event.name, Event.id)
    )
    return [EventOut.model_validate(e) for e in result.scalars().all()]


@router.get("/managed", response_model=list[EventOut])
async def managed_events(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """The events this organizer may manage (admins: all). Declared before
    /{event_id} so "managed" is never read as an event id."""
    stmt = select(Event).options(*_EVENT_LOAD).order_by(Event.submissions_close, Event.name, Event.id)
    if user.role != UserRole.ADMIN:
        stmt = stmt.where(Event.owner_id == user.id)
    return [EventOut.model_validate(e) for e in (await db.execute(stmt)).scalars().all()]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    return EventOut.model_validate(await get_event_or_404(db, event_id, with_children=True))


@router.get("/{event_id}/criteria", response_model=list[CriterionOut])
async def get_criteria(event_id: str, db: AsyncSession = Depends(get_db)):
    """The event's published rubric. Public on purpose: participants see
    what they'll be judged on, judges see what to score against."""
    await get_event_or_404(db, event_id)
    result = await db.execute(
        select(JudgingCriterion).where(JudgingCriterion.event_id == event_id).order_by(JudgingCriterion.name)
    )
    return [CriterionOut.model_validate(c) for c in result.scalars().all()]


@router.post("/{event_id}/criteria", response_model=list[CriterionOut])
async def set_criteria(
    event_id: str,
    payload: list[CriterionCreate],
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Organizer-configurable weighted rubric -- replaces any existing
    criteria for this event with the new list."""
    await get_owned_event(db, event_id, organizer)

    names = [c.name.strip().lower() for c in payload]
    if len(set(names)) != len(names):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Criterion names must be unique.")

    existing = await db.execute(select(JudgingCriterion).where(JudgingCriterion.event_id == event_id))
    for c in existing.scalars().all():
        await db.delete(c)
    await db.flush()

    created = [
        JudgingCriterion(event_id=event_id, name=c.name.strip(), weight=c.weight, description=c.description)
        for c in payload
    ]
    for c in created:
        db.add(c)
    await audit(db, "criteria.update", event_id=event_id, actor=organizer, target_type="event", target_id=event_id,
                detail={c.name: float(c.weight) for c in created})
    await db.commit()
    for c in created:
        await db.refresh(c)
    return [CriterionOut.model_validate(c) for c in created]


async def _conflict_count(db: AsyncSession, event_id: str) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(ConflictDeclaration)
            .join(
                JudgeAssignment,
                and_(
                    JudgeAssignment.judge_user_id == ConflictDeclaration.judge_user_id,
                    JudgeAssignment.project_id == ConflictDeclaration.project_id,
                ),
            )
            .where(JudgeAssignment.event_id == event_id)
        )
    ) or 0


@router.get("/{event_id}/stats", response_model=EventStats)
async def event_stats(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Real counts for the organizer overview -- nothing estimated."""
    await get_owned_event(db, event_id, organizer)

    teams = await db.scalar(select(func.count()).select_from(Team).where(Team.event_id == event_id))
    participants = await db.scalar(
        select(func.count(distinct(TeamMember.user_id)))
        .select_from(TeamMember)
        .join(Team, Team.id == TeamMember.team_id)
        .where(Team.event_id == event_id)
    )
    submissions = await db.scalar(
        select(func.count())
        .select_from(Project)
        .join(Team, Team.id == Project.team_id)
        .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT)
    )
    judges_assigned = await db.scalar(
        select(func.count(distinct(JudgeAssignment.judge_user_id))).where(JudgeAssignment.event_id == event_id)
    )
    assigned = await db.scalar(
        select(func.count()).select_from(JudgeAssignment).where(JudgeAssignment.event_id == event_id)
    )
    reviews_done = await db.scalar(
        select(func.count())
        .select_from(Score)
        .join(
            JudgeAssignment,
            and_(JudgeAssignment.judge_user_id == Score.judge_user_id, JudgeAssignment.project_id == Score.project_id),
        )
        .where(JudgeAssignment.event_id == event_id)
    )
    conflicts = await _conflict_count(db, event_id)
    return EventStats(
        teams=teams or 0,
        participants=participants or 0,
        submissions=submissions or 0,
        judges_assigned=judges_assigned or 0,
        # A declared conflict is not a review anyone owes.
        reviews_assigned=max(0, (assigned or 0) - conflicts),
        reviews_done=reviews_done or 0,
    )


@router.get("/{event_id}/submissions", response_model=list[SubmissionRow])
async def event_submissions(
    event_id: str,
    round_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Every submitted project with its review coverage."""
    await get_owned_event(db, event_id, organizer)

    stmt = (
        select(Project, Team.name, Track.name, Round.id, Round.number, Round.name)
        .join(Team, Team.id == Project.team_id)
        .outerjoin(Track, Track.id == Project.track_id)
        .outerjoin(Round, Round.id == Project.round_id)
        .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT)
        .order_by(Round.number, Project.submitted_at.desc())
    )
    if round_id:
        stmt = stmt.where(Project.round_id == round_id)
    rows = (await db.execute(stmt)).all()

    assigned = dict(
        (
            await db.execute(
                select(JudgeAssignment.project_id, func.count())
                .where(JudgeAssignment.event_id == event_id)
                .group_by(JudgeAssignment.project_id)
            )
        ).all()
    )
    reviewed = dict(
        (
            await db.execute(
                select(Score.project_id, func.count())
                .join(
                    JudgeAssignment,
                    and_(
                        JudgeAssignment.judge_user_id == Score.judge_user_id,
                        JudgeAssignment.project_id == Score.project_id,
                    ),
                )
                .where(JudgeAssignment.event_id == event_id)
                .group_by(Score.project_id)
            )
        ).all()
    )
    return [
        SubmissionRow(
            project_id=project.id, title=project.title, team_name=team_name, track_name=track_name,
            submitted_at=project.submitted_at, round_id=rid, round_number=rnum, round_name=rname,
            assigned=assigned.get(project.id, 0), reviewed=reviewed.get(project.id, 0),
        )
        for project, team_name, track_name, rid, rnum, rname in rows
    ]


@router.get("/{event_id}/progress", response_model=list[ProgressOut])
async def judging_progress(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Live view of who's finished judging and who hasn't."""
    await get_owned_event(db, event_id, organizer)
    assignments = (
        await db.execute(select(JudgeAssignment).where(JudgeAssignment.event_id == event_id))
    ).scalars().all()
    conflicts = {
        (c.judge_user_id, c.project_id)
        for c in (await db.execute(select(ConflictDeclaration))).scalars().all()
    }

    by_judge: dict[str, list[str]] = {}
    for a in assignments:
        if (a.judge_user_id, a.project_id) not in conflicts:
            by_judge.setdefault(a.judge_user_id, []).append(a.project_id)

    rows: list[ProgressOut] = []
    for judge_id, project_ids in by_judge.items():
        judge = (await db.execute(select(User).where(User.id == judge_id))).scalar_one_or_none()
        scored = await db.execute(select(Score).where(Score.judge_user_id == judge_id, Score.project_id.in_(project_ids)))
        rows.append(
            ProgressOut(
                judge_user_id=judge_id,
                judge_email=judge.email if judge else "unknown",
                judge_name=judge.name if judge else "",
                assigned=len(project_ids),
                completed=len(scored.scalars().all()),
            )
        )
    rows.sort(key=lambda r: r.judge_name.lower())
    return rows


@router.get("/{event_id}/results", response_model=list[ResultRow])
async def event_results(
    event_id: str,
    round_id: Optional[str] = Query(default=None, description="Defaults to the latest round with assigned work"),
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Ranking for one round using the documented normalization method --
    see JUDGING.md. Computed on demand, not cached."""
    await get_owned_event(db, event_id, organizer)
    rnd = await resolve_round(db, event_id, round_id)
    return [ResultRow(**r) for r in await compute_results(db, event_id, rnd)]


@router.get("/{event_id}/pairwise-results", response_model=list[PairwiseRankRow])
async def pairwise_results(
    event_id: str,
    round_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Bradley-Terry ranking from head-to-head comparisons -- the
    Pairwise Mode bonus challenge, an alternative view alongside /results."""
    await get_owned_event(db, event_id, organizer)
    rnd = await resolve_round(db, event_id, round_id)
    round_projects = None
    if rnd is not None:
        round_projects = {
            row[0] for row in (await db.execute(select(Project.id).where(Project.round_id == rnd.id))).all()
        }

    comparisons = (
        await db.execute(select(PairwiseComparison).where(PairwiseComparison.event_id == event_id))
    ).scalars().all()
    if round_projects is not None:
        comparisons = [c for c in comparisons if c.project_a_id in round_projects and c.project_b_id in round_projects]
    if not comparisons:
        return []

    project_ids: set[str] = set()
    pairs: list[tuple[str, str]] = []
    comparison_counts: dict[str, int] = defaultdict(int)
    for c in comparisons:
        loser_id = c.project_b_id if c.winner_id == c.project_a_id else c.project_a_id
        pairs.append((c.winner_id, loser_id))
        project_ids.update((c.project_a_id, c.project_b_id))
        comparison_counts[c.project_a_id] += 1
        comparison_counts[c.project_b_id] += 1

    strengths = bradley_terry_strengths(list(project_ids), pairs)
    titles = {
        p.id: p.title for p in (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
    }
    teams = await _team_names(db, project_ids)
    rows = [
        PairwiseRankRow(
            project_id=pid, project_title=titles.get(pid, ""), team_name=teams.get(pid, ""),
            strength=strength, comparisons=comparison_counts[pid],
        )
        for pid, strength in strengths.items()
    ]
    rows.sort(key=lambda r: r.strength, reverse=True)
    return rows


@router.get("/{event_id}/teams", response_model=list[TeamRow])
async def event_teams(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    """Every team in the event (organizer-only), for extension/advancement pickers."""
    await get_owned_event(db, event_id, organizer)
    members = dict((await db.execute(
        select(TeamMember.team_id, func.count()).join(Team, Team.id == TeamMember.team_id).where(Team.event_id == event_id).group_by(TeamMember.team_id)
    )).all())
    subs = dict((await db.execute(
        select(Project.team_id, func.count()).join(Team, Team.id == Project.team_id)
        .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT).group_by(Project.team_id)
    )).all())
    teams = (await db.execute(select(Team).where(Team.event_id == event_id).order_by(Team.name))).scalars().all()
    return [TeamRow(id=t.id, name=t.name, members=members.get(t.id, 0), submitted_rounds=subs.get(t.id, 0)) for t in teams]
