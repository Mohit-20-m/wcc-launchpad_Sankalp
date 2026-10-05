"""
Submissions. POST is a *submission*: one per team per round, and
submitting again REPLACES the previous one (its files are deleted too),
so a team never piles up stale copies. PATCH edits in place. Everything
is checked against the round's rules and the real server clock -- never
anything the client sends.

Also home to two rules everything else relies on: the public gallery
(no auth) and rejecting submissions once an event or round has closed.

Files are private: only the team, the judges assigned to the project and
the event's organizer can download them.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import can_manage
from app.core.security import get_current_user
from app.models.event import Event, Track
from app.models.judging import ConflictDeclaration, JudgeAssignment
from app.models.project import Project, ProjectFile, SubmissionStatus
from app.models.round import Round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.schemas.projects import ProjectCreate, ProjectFileOut, ProjectOut, ProjectPublic, ProjectUpdate
from app.core.net import request_ip_hash
from app.services import files as filesvc
from app.services.audit import audit
from app.api.routes.integrity import flag_similar
from app.services.live import hub
from app.services.submissions import (
    delete_project_files,
    enforce_round_fields,
    pick_round,
    project_out,
    require_open_for_team,
    validate_track,
)

router = APIRouter()
MAX_FILES_PER_PROJECT = 10


async def _team_and_event(db: AsyncSession, team_id: str, lock: bool = False) -> tuple[Team, Event]:
    stmt = select(Team).where(Team.id == team_id)
    if lock:
        # Serialise concurrent submissions from one team (Postgres row
        # lock; a no-op on SQLite) so two clicks can't create two rows.
        stmt = stmt.with_for_update()
    team = (await db.execute(stmt)).scalar_one_or_none()
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    event = (await db.execute(select(Event).where(Event.id == team.event_id))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found.")
    return team, event


async def _require_member(db: AsyncSession, team_id: str, user_id: str) -> None:
    ok = (
        await db.execute(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    ).scalar_one_or_none()
    if ok is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this team.")


async def _project(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


async def _project_round(db: AsyncSession, project: Project, event_id: str) -> Round:
    rnd = None
    if project.round_id:
        rnd = (await db.execute(select(Round).where(Round.id == project.round_id))).scalar_one_or_none()
    if rnd is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project isn't attached to a round.")
    return rnd


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def submit_project(
    payload: ProjectCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team, event = await _team_and_event(db, payload.team_id, lock=True)
    await _require_member(db, team.id, current_user.id)

    if payload.round_id:
        rnd = (await db.execute(select(Round).where(Round.id == payload.round_id, Round.event_id == event.id))).scalar_one_or_none()
        if rnd is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found for this event.")
    else:
        rnd = await pick_round(db, event.id, team.id)

    await require_open_for_team(db, rnd, team.id)
    fields = payload.model_dump()
    enforce_round_fields(rnd, fields)
    await validate_track(db, event.id, payload.track_id)

    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(select(Project).where(Project.team_id == team.id, Project.round_id == rnd.id))
    ).scalar_one_or_none()

    replaced_files = 0
    if existing is None:
        project = Project(team_id=team.id, round_id=rnd.id)
        db.add(project)
        action = "submission.create"
    else:
        # A new submission replaces the old one: same record (so votes,
        # comments and history stay attached), old content and FILES gone.
        project = existing
        replaced_files = await delete_project_files(db, project.id)
        action = "submission.replace"

    project.track_id = payload.track_id
    project.title = payload.title
    project.summary = payload.summary
    project.repo_url = payload.repo_url
    project.tech_stack = payload.tech_stack
    project.video_url = payload.video_url
    project.status = SubmissionStatus.SUBMITTED
    project.submitted_at = now
    project.updated_at = now
    await db.flush()
    await audit(db, action, event_id=event.id, actor=current_user, target_type="project", target_id=project.id,
                detail={"team": team.name, "round": rnd.number, "files_deleted": replaced_files},
                ip_hash=request_ip_hash(request))
    try:  # resemblance to another submission is recorded for the organizer; it never blocks
        if await flag_similar(db, event.id, project.id):
            await hub.publish(event.id, "similarity")
    except Exception:  # noqa: BLE001
        pass
    await db.commit()
    await hub.publish(event.id, "stats", "submissions")
    return await project_out(db, project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _project(db, project_id)
    team, event = await _team_and_event(db, project.team_id)
    await _require_member(db, team.id, current_user.id)
    rnd = await _project_round(db, project, event.id)
    if project.status == SubmissionStatus.LOCKED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This project can no longer be edited.")
    await require_open_for_team(db, rnd, team.id)

    changes = payload.model_dump(exclude_unset=True)
    enforce_round_fields(rnd, changes)
    await validate_track(db, event.id, changes.get("track_id"))
    for field, value in changes.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)
    await audit(db, "submission.edit", event_id=event.id, actor=current_user, target_type="project", target_id=project.id,
                detail={"fields": sorted(changes)})
    await db.commit()
    await hub.publish(event.id, "submissions")
    return await project_out(db, project)


# --------------------------------- files ---------------------------------

@router.post("/{project_id}/files", response_model=ProjectFileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _project(db, project_id)
    team, event = await _team_and_event(db, project.team_id)
    await _require_member(db, team.id, current_user.id)
    rnd = await _project_round(db, project, event.id)
    await require_open_for_team(db, rnd, team.id)
    if not rnd.allow_files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{rnd.name} doesn't accept file uploads.")

    count = len((await db.execute(select(ProjectFile).where(ProjectFile.project_id == project.id))).scalars().all())
    if count >= MAX_FILES_PER_PROJECT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A submission can have at most {MAX_FILES_PER_PROJECT} files.")

    stored, name, ctype, size = await filesvc.save_upload(file, set(rnd.file_types.split(",")), rnd.max_file_mb)
    row = ProjectFile(
        project_id=project.id, filename=name, stored_name=stored, content_type=ctype, size_bytes=size,
        uploaded_by=current_user.id, uploaded_at=datetime.now(timezone.utc),
    )
    db.add(row)
    project.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await audit(db, "file.upload", event_id=event.id, actor=current_user, target_type="project", target_id=project.id,
                detail={"file": name, "bytes": size})
    await db.commit()
    await db.refresh(row)
    await hub.publish(event.id, "submissions")
    return ProjectFileOut.model_validate(row)


@router.delete("/{project_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    project_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _project(db, project_id)
    team, event = await _team_and_event(db, project.team_id)
    await _require_member(db, team.id, current_user.id)
    rnd = await _project_round(db, project, event.id)
    await require_open_for_team(db, rnd, team.id)
    row = (await db.execute(select(ProjectFile).where(ProjectFile.id == file_id, ProjectFile.project_id == project.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    filesvc.delete_stored(row.stored_name)
    await db.delete(row)
    await audit(db, "file.delete", event_id=event.id, actor=current_user, target_type="project", target_id=project.id,
                detail={"file": row.filename})
    await db.commit()
    await hub.publish(event.id, "submissions")


@router.get("/{project_id}/files/{file_id}")
async def download_file(
    project_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Private download: the team, a judge assigned to this project (who
    hasn't declared a conflict), or the event's organizer. Nobody else --
    not other teams, not other judges, not the public."""
    project = await _project(db, project_id)
    team, event = await _team_and_event(db, project.team_id)

    allowed = can_manage(event, current_user)
    if not allowed:
        allowed = (
            await db.execute(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == current_user.id))
        ).scalar_one_or_none() is not None
    if not allowed and current_user.role == UserRole.JUDGE:
        assigned = (
            await db.execute(select(JudgeAssignment).where(JudgeAssignment.judge_user_id == current_user.id, JudgeAssignment.project_id == project.id))
        ).scalar_one_or_none()
        conflict = (
            await db.execute(select(ConflictDeclaration).where(ConflictDeclaration.judge_user_id == current_user.id, ConflictDeclaration.project_id == project.id))
        ).scalar_one_or_none()
        allowed = assigned is not None and conflict is None
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this file.")

    row = (await db.execute(select(ProjectFile).where(ProjectFile.id == file_id, ProjectFile.project_id == project.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    return FileResponse(
        filesvc.stored_path(row.stored_name),
        media_type=row.content_type,
        filename=row.filename,
        content_disposition_type="attachment",  # never rendered inline by the browser
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


# --------------------------------- gallery --------------------------------

def _public(project: Project, team_name: str, track_name: Optional[str], event: Event, round_number: Optional[int]) -> ProjectPublic:
    base = ProjectOut.model_validate(project).model_dump(exclude={"files"})
    return ProjectPublic(**base, team_name=team_name, track_name=track_name, event_id=event.id,
                         event_name=event.name, round_number=round_number)


@router.get("", response_model=list[ProjectPublic])
async def gallery(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, description="Search project titles"),
    track_id: Optional[str] = Query(default=None),
    event_id: Optional[str] = Query(default=None),
):
    # Public, no auth required: anyone can browse what's been built.
    # A team appears once, with its most recent round's submission.
    stmt = (
        select(Project, Team.name, Track.name, Event, Round.number)
        .join(Team, Team.id == Project.team_id)
        .join(Event, Event.id == Team.event_id)
        .outerjoin(Track, Track.id == Project.track_id)
        .outerjoin(Round, Round.id == Project.round_id)
        .where(Project.status.in_([SubmissionStatus.SUBMITTED, SubmissionStatus.LOCKED]))
    )
    if q:
        stmt = stmt.where(Project.title.ilike(f"%{q}%"))
    if track_id:
        stmt = stmt.where(Project.track_id == track_id)
    if event_id:
        stmt = stmt.where(Team.event_id == event_id)

    all_rows = (await db.execute(stmt)).all()
    top_round: dict[str, int] = {}
    for project, _tn, _trk, _ev, rnum in all_rows:
        top_round[project.team_id] = max(top_round.get(project.team_id, 0), rnum or 0)
    return [
        _public(p, tn, trk, ev, rnum)
        for p, tn, trk, ev, rnum in all_rows
        if (rnum or 0) == top_round[p.team_id]
    ]


@router.get("/{project_id}", response_model=ProjectPublic)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(Project, Team.name, Track.name, Event, Round.number)
            .join(Team, Team.id == Project.team_id)
            .join(Event, Event.id == Team.event_id)
            .outerjoin(Track, Track.id == Project.track_id)
            .outerjoin(Round, Round.id == Project.round_id)
            .where(Project.id == project_id)
        )
    ).first()
    if row is None or row[0].status == SubmissionStatus.DRAFT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    project, tn, trk, ev, rnum = row
    return _public(project, tn, trk, ev, rnum)
