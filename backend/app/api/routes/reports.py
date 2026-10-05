"""CSV export of judging scores -- organizer-only, one event at a time.

DATA ISOLATION: an export covers exactly ONE event, chosen with
?event_id=. An organizer can only export events they own. With no
event_id the export is for the organizer's most recently created event
(never "everything"), and the X-Export-Event header says which."""

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.event import Event
from app.models.judging import Score
from app.models.project import Project
from app.models.round import Round
from app.models.team import Team
from app.models.user import User, UserRole
from app.services.audit import audit
from app.services.csvsafe import safe_cell

router = APIRouter()

HEADER = ["event_id", "event_name", "round", "project_id", "project_title", "team_name", "judge_user_id", "criteria", "comment"]


@router.get("/export.csv")
async def export_csv(
    event_id: Optional[str] = Query(default=None, description="The event to export (default: your newest)"),
    db: AsyncSession = Depends(get_db),
    organizer: User = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN)),
):
    event: Optional[Event] = None
    if event_id:
        event = await get_owned_event(db, event_id, organizer)  # 404 unknown, 403 not yours
    else:
        stmt = select(Event).order_by(Event.created_at.desc(), Event.id)
        if organizer.role != UserRole.ADMIN:
            stmt = stmt.where(Event.owner_id == organizer.id)
        event = (await db.execute(stmt.limit(1))).scalar_one_or_none()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(HEADER)

    if event is not None:
        rows = (
            await db.execute(
                select(Score, Project, Team.name, Round.number)
                .join(Project, Project.id == Score.project_id)
                .join(Team, Team.id == Project.team_id)
                .outerjoin(Round, Round.id == Project.round_id)
                .where(Team.event_id == event.id)
                .order_by(Round.number, Project.title, Score.judge_user_id)
            )
        ).all()
        for score, project, team_name, rnum in rows:
            writer.writerow([
                event.id, safe_cell(event.name), rnum or "", project.id, safe_cell(project.title), safe_cell(team_name),
                score.judge_user_id, safe_cell(str(score.criteria)), safe_cell(score.comment or ""),
            ])
        await audit(db, "export.scores", event_id=event.id, actor=organizer, target_type="event", target_id=event.id, detail={"rows": len(rows)})
        await db.commit()

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=scores_{(event.id if event else 'none')}.csv",
            "X-Export-Event": event.id if event else "",
        },
    )
