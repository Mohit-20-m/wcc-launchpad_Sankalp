"""Rules for what a team may submit, and when. Used by the project
routes so that create, edit and file upload all obey the same checks."""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Track
from app.models.project import Project, ProjectFile
from app.models.round import Round, RoundAdvancement
from app.schemas.projects import ProjectFileOut, ProjectOut
from app.services.files import delete_stored
from app.services.rounds import get_rounds, team_round_state


async def project_out(db: AsyncSession, project: Project) -> ProjectOut:
    files = (
        await db.execute(select(ProjectFile).where(ProjectFile.project_id == project.id).order_by(ProjectFile.uploaded_at))
    ).scalars().all()
    return ProjectOut.model_validate(project).model_copy(
        update={"files": [ProjectFileOut.model_validate(f) for f in files]}
    )


async def team_can_enter(db: AsyncSession, rnd: Round, team_id: str) -> bool:
    if rnd.open_to_all:
        return True
    return (
        await db.execute(
            select(RoundAdvancement).where(RoundAdvancement.round_id == rnd.id, RoundAdvancement.team_id == team_id)
        )
    ).scalar_one_or_none() is not None


async def pick_round(db: AsyncSession, event_id: str, team_id: str) -> Round:
    """The round a team is working on: the first one that is open to them
    right now, else the latest one they're eligible for."""
    rounds = await get_rounds(db, event_id)
    if not rounds:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This event has no rounds set up.")
    eligible = [r for r in rounds if await team_can_enter(db, r, team_id)]
    for r in eligible:
        if await team_round_state(db, r, team_id) == "open":
            return r
    return (eligible or rounds)[-1]


async def require_open_for_team(db: AsyncSession, rnd: Round, team_id: str) -> None:
    if not await team_can_enter(db, rnd, team_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your team hasn't advanced to {rnd.name}.")
    state = await team_round_state(db, rnd, team_id)
    if state == "not_open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{rnd.name} hasn't opened for submissions yet.")
    if state == "closed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Submissions are closed for {rnd.name}.")


def enforce_round_fields(rnd: Round, data: dict) -> None:
    """Reject anything the round doesn't accept. Empty values are fine."""
    rules = [
        ("summary", rnd.allow_idea, "an idea description"),
        ("tech_stack", rnd.allow_idea, "a tech stack"),
        ("repo_url", rnd.allow_repo, "a repository link"),
        ("video_url", rnd.allow_video, "a video link"),
    ]
    for field, allowed, label in rules:
        if not allowed and (data.get(field) or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{rnd.name} doesn't accept {label}.")


async def validate_track(db: AsyncSession, event_id: str, track_id: Optional[str]) -> None:
    if not track_id:
        return
    ok = (
        await db.execute(select(Track).where(Track.id == track_id, Track.event_id == event_id))
    ).scalar_one_or_none()
    if ok is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That track doesn't belong to this event.")


async def delete_project_files(db: AsyncSession, project_id: str) -> int:
    """Remove a project's files from the database AND from disk."""
    files = (await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id))).scalars().all()
    for f in files:
        delete_stored(f.stored_name)
        await db.delete(f)
    return len(files)
