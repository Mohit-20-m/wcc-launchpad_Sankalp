"""
Judge assignment and scoring.

THE MOST IMPORTANT ROUTE IN THIS FILE is my_scores below. It enforces
the platform's most important fairness rule: a judge must never
be able to read a peer's scores, and that check has to live here, in
the backend, because this is where curl arrives -- a hidden button in
the frontend proves nothing to an API client.

Scoring opens only after a project's round has closed its submissions
(deadline passed, or the organizer stopped them early), and never on a
project the judge declared a conflict of interest on. Both rules are
enforced here, in the API.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.event import Event, Track
from app.models.judging import ConflictDeclaration, JudgeAssignment, Score
from app.models.project import Project, ProjectFile
from app.models.round import Round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.schemas.judging import (
    AssignmentCreate,
    AssignmentOut,
    ConflictDeclare,
    JudgeOut,
    QueueFile,
    QueueItem,
    ScoreOut,
    ScoreSubmit,
)
from app.services.audit import audit
from app.services.judging_rules import has_conflict, project_state
from app.services.live import hub

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))


@router.post("/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    payload: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    organizer: User = Organizer,
):
    judge = (await db.execute(select(User).where(User.email == payload.judge_email))).scalar_one_or_none()
    if judge is None or judge.role != UserRole.JUDGE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No judge with that email.")

    project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    team = (await db.execute(select(Team).where(Team.id == project.team_id))).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project's team not found.")

    # Data isolation: you can only assign judges to YOUR event's projects.
    await get_owned_event(db, team.event_id, organizer)

    # Automatic conflict of interest: a judge can't review their own team.
    on_team = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == judge.id))
    ).scalar_one_or_none()
    if on_team is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That judge is a member of this project's team.")

    existing = await db.execute(
        select(JudgeAssignment).where(JudgeAssignment.judge_user_id == judge.id, JudgeAssignment.project_id == project.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already assigned.")

    assignment = JudgeAssignment(event_id=team.event_id, judge_user_id=judge.id, project_id=project.id)
    db.add(assignment)
    await audit(db, "judge.assign", event_id=team.event_id, actor=organizer, target_type="project", target_id=project.id,
                detail={"judge": judge.email, "project": project.title})
    await db.commit()
    await db.refresh(assignment)
    await hub.publish(team.event_id, "progress", "stats", "submissions")
    return AssignmentOut.model_validate(assignment)


@router.delete("/assignments/{judge_user_id}/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_assignment(
    judge_user_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    organizer: User = Organizer,
):
    """Unassign (e.g. after a declared conflict). Refused once the judge
    has already scored the project -- their review is part of the record."""
    assignment = (
        await db.execute(
            select(JudgeAssignment).where(JudgeAssignment.judge_user_id == judge_user_id, JudgeAssignment.project_id == project_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such assignment.")
    await get_owned_event(db, assignment.event_id, organizer)
    scored = (
        await db.execute(select(Score).where(Score.judge_user_id == judge_user_id, Score.project_id == project_id))
    ).scalar_one_or_none()
    if scored is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This judge has already scored the project; the review can't be removed.")
    for c in (
        await db.execute(select(ConflictDeclaration).where(ConflictDeclaration.judge_user_id == judge_user_id, ConflictDeclaration.project_id == project_id))
    ).scalars().all():
        await db.delete(c)
    await db.delete(assignment)
    await audit(db, "judge.unassign", event_id=assignment.event_id, actor=organizer, target_type="project", target_id=project_id,
                detail={"judge_user_id": judge_user_id})
    await db.commit()
    await hub.publish(assignment.event_id, "progress", "stats", "submissions", "conflicts")


@router.get("/assignments/mine", response_model=list[AssignmentOut])
async def my_assignments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    result = await db.execute(select(JudgeAssignment).where(JudgeAssignment.judge_user_id == current_user.id))
    return [AssignmentOut.model_validate(a) for a in result.scalars().all()]


@router.get("/queue", response_model=list[QueueItem])
async def my_queue(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    """The judge's assigned projects with EVERYTHING the team submitted
    (text, links, files), plus whether scoring is open yet. Only ever
    returns the caller's own assignments."""
    rows = (
        await db.execute(
            select(Project, Team.name, Track.name, Event.id, Event.name)
            .join(JudgeAssignment, JudgeAssignment.project_id == Project.id)
            .join(Team, Team.id == Project.team_id)
            .join(Event, Event.id == Team.event_id)
            .outerjoin(Track, Track.id == Project.track_id)
            .where(JudgeAssignment.judge_user_id == current_user.id)
            .order_by(Project.title)
        )
    ).all()

    scored_ids = {r[0] for r in (await db.execute(select(Score.project_id).where(Score.judge_user_id == current_user.id))).all()}
    conflict_ids = {
        r[0] for r in (await db.execute(select(ConflictDeclaration.project_id).where(ConflictDeclaration.judge_user_id == current_user.id))).all()
    }
    project_ids = [r[0].id for r in rows]
    files_by_project: dict[str, list[QueueFile]] = {}
    if project_ids:
        for f in (
            await db.execute(select(ProjectFile).where(ProjectFile.project_id.in_(project_ids)).order_by(ProjectFile.uploaded_at))
        ).scalars().all():
            files_by_project.setdefault(f.project_id, []).append(
                QueueFile(id=f.id, filename=f.filename, content_type=f.content_type, size_bytes=f.size_bytes)
            )

    items: list[QueueItem] = []
    for project, team_name, track_name, event_id, event_name in rows:
        rnd, state = await project_state(db, project)
        conflict = project.id in conflict_ids
        items.append(
            QueueItem(
                project_id=project.id, project_title=project.title, project_summary=project.summary,
                repo_url=project.repo_url, tech_stack=project.tech_stack, video_url=project.video_url,
                team_name=team_name, track_name=track_name, event_id=event_id, event_name=event_name,
                scored=project.id in scored_ids,
                round_id=rnd.id if rnd else None, round_name=rnd.name if rnd else None,
                round_number=rnd.number if rnd else None,
                scorable=(state == "closed") and not conflict, conflict=conflict,
                files=files_by_project.get(project.id, []),
            )
        )
    return items


@router.get("/judges", response_model=list[JudgeOut])
async def list_judges(db: AsyncSession = Depends(get_db), _organizer: User = Organizer):
    """Every account with the Judge role -- lets an organizer pick from a
    list instead of typing an email from memory."""
    result = await db.execute(select(User).where(User.role == UserRole.JUDGE).order_by(User.name))
    return [JudgeOut(id=u.id, name=u.name, email=u.email) for u in result.scalars().all()]


@router.post("/conflicts", status_code=status.HTTP_201_CREATED)
async def declare_conflict(
    payload: ConflictDeclare,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    """Declare a conflict of interest on an assigned project. The judge
    can then no longer score or compare it; the organizer is told and can
    reassign it."""
    assignment = (
        await db.execute(
            select(JudgeAssignment).where(JudgeAssignment.judge_user_id == current_user.id, JudgeAssignment.project_id == payload.project_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not assigned to this project.")
    if (
        await db.execute(select(Score).where(Score.judge_user_id == current_user.id, Score.project_id == payload.project_id))
    ).scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already scored this project. Ask an organizer to handle it.")
    if await has_conflict(db, current_user.id, payload.project_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already declared a conflict on this project.")
    db.add(ConflictDeclaration(judge_user_id=current_user.id, project_id=payload.project_id, reason=payload.reason))
    await audit(db, "judge.conflict", event_id=assignment.event_id, actor=current_user, target_type="project",
                target_id=payload.project_id, detail={"reason": payload.reason})
    await db.commit()
    await hub.publish(assignment.event_id, "progress", "conflicts", "stats")
    return {"status": "declared"}


@router.post("/scores", response_model=ScoreOut, status_code=status.HTTP_201_CREATED)
async def submit_score(
    payload: ScoreSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    assignment = (
        await db.execute(
            select(JudgeAssignment).where(JudgeAssignment.judge_user_id == current_user.id, JudgeAssignment.project_id == payload.project_id)
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not assigned to review this project.")

    if await has_conflict(db, current_user.id, payload.project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You declared a conflict of interest on this project.")

    project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one()
    rnd, state = await project_state(db, project)
    if state != "closed":
        # A team can still change this work; scoring it now would score a moving target.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Scoring opens when submissions for {rnd.name if rnd else 'this round'} close.",
        )

    score = (
        await db.execute(select(Score).where(Score.judge_user_id == current_user.id, Score.project_id == payload.project_id))
    ).scalar_one_or_none()
    if score is None:
        score = Score(judge_user_id=current_user.id, project_id=payload.project_id, criteria=payload.criteria, comment=payload.comment)
        db.add(score)
        action = "score.submit"
    else:
        score.criteria = payload.criteria
        score.comment = payload.comment
        action = "score.update"

    # The audit row records THAT a review happened -- never the numbers.
    await audit(db, action, event_id=assignment.event_id, actor=current_user, target_type="project", target_id=project.id)
    await db.commit()
    await db.refresh(score)
    await hub.publish(assignment.event_id, "progress", "stats", "submissions")
    return ScoreOut.model_validate(score)


@router.get("/scores", response_model=list[ScoreOut])
async def my_scores(
    judge: Optional[str] = Query(default=None, description="A judge's email -- only your own is allowed"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    # THE privacy check. A judge asking for someone else's scores --
    # by email, in this design -- gets refused here, at the API layer,
    # regardless of what any frontend button does or doesn't show.
    if judge is not None and judge != current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own scores.")

    result = await db.execute(select(Score).where(Score.judge_user_id == current_user.id))
    return [ScoreOut.model_validate(s) for s in result.scalars().all()]
