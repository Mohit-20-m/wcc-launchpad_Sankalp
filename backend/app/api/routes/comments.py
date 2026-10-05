"""Comments on gallery projects. Anyone signed in can comment (rate
limited); organizers can hide comments (soft delete, audited)."""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import can_manage, get_owned_event
from app.core.security import get_current_user, get_optional_user
from app.models.event import Event
from app.models.project import Project, SubmissionStatus
from app.models.team import Team
from app.models.user import User
from app.models.voting import Comment
from app.schemas.extras import CommentIn, CommentOut
from app.services.audit import audit
from app.services.live import hub
from app.services.ratelimit import limiter
from app.services.rounds import now_utc

router = APIRouter()
PER_MINUTE = (5, 60)
PER_DAY = (60, 86400)


async def _public_project(db: AsyncSession, project_id: str) -> tuple[Project, str]:
    row = (
        await db.execute(select(Project, Team.event_id).join(Team, Team.id == Project.team_id).where(Project.id == project_id))
    ).first()
    if row is None or row[0].status == SubmissionStatus.DRAFT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return row[0], row[1]


@router.get("/projects/{project_id}/comments", response_model=list[CommentOut])
async def list_comments(project_id: str, db: AsyncSession = Depends(get_db), user: Optional[User] = Depends(get_optional_user)):
    _project, event_id = await _public_project(db, project_id)
    event = (await db.execute(select(Event).where(Event.id == event_id))).scalar_one()
    is_organizer = bool(user and can_manage(event, user))
    rows = (
        await db.execute(
            select(Comment, User.name).join(User, User.id == Comment.user_id)
            .where(Comment.project_id == project_id).order_by(Comment.created_at.desc()).limit(200)
        )
    ).all()
    return [
        CommentOut(id=c.id, project_id=c.project_id, author_name=name, body=c.body, created_at=c.created_at, hidden=c.hidden_at is not None)
        for c, name in rows
        if c.hidden_at is None or is_organizer  # hidden comments are for organizers only
    ]


@router.post("/projects/{project_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(project_id: str, payload: CommentIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    _project, event_id = await _public_project(db, project_id)
    if not await limiter.allow(f"comment:min:{user.id}", *PER_MINUTE) or not await limiter.allow(f"comment:day:{user.id}", *PER_DAY):
        await audit(db, "comment.rate_limited", event_id=event_id, actor=user, target_type="project", target_id=project_id)
        await db.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You're commenting too fast. Wait a minute.")
    comment = Comment(project_id=project_id, user_id=user.id, body=payload.body)
    db.add(comment)
    await db.flush()
    await audit(db, "comment.create", event_id=event_id, actor=user, target_type="project", target_id=project_id)
    await db.commit()
    await db.refresh(comment)
    await hub.publish(event_id, "comments")
    return CommentOut(id=comment.id, project_id=project_id, author_name=user.name, body=comment.body, created_at=comment.created_at)


async def _set_hidden(db: AsyncSession, comment_id: str, organizer: User, hide: bool) -> None:
    comment = (await db.execute(select(Comment).where(Comment.id == comment_id))).scalar_one_or_none()
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found.")
    _project, event_id = await _public_project(db, comment.project_id)
    await get_owned_event(db, event_id, organizer)  # only the event's organizer moderates
    comment.hidden_at, comment.hidden_by = (now_utc(), organizer.id) if hide else (None, None)
    await audit(db, "comment.hide" if hide else "comment.unhide", event_id=event_id, actor=organizer, target_type="comment", target_id=comment_id)
    await db.commit()
    await hub.publish(event_id, "comments", "audit")


@router.post("/comments/{comment_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
async def hide_comment(comment_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _set_hidden(db, comment_id, user, True)


@router.post("/comments/{comment_id}/unhide", status_code=status.HTTP_204_NO_CONTENT)
async def unhide_comment(comment_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _set_hidden(db, comment_id, user, False)
