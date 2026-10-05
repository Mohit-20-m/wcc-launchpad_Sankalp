"""When may a judge score a project? Only after its round's submissions
have closed (deadline passed, or the organizer stopped them early) --
judges must not score work a team can still change -- and never on a
project they declared a conflict of interest on."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.judging import ConflictDeclaration, JudgeAssignment
from app.models.project import Project
from app.models.round import Round
from app.services.rounds import team_round_state


async def project_state(db: AsyncSession, project: Project) -> tuple[Optional[Round], str]:
    """(round, state) where state is the team-specific not_open|open|closed."""
    rnd = None
    if project.round_id:
        rnd = (await db.execute(select(Round).where(Round.id == project.round_id))).scalar_one_or_none()
    if rnd is None:
        return None, "closed"  # legacy project with no round: nothing left to wait for
    return rnd, await team_round_state(db, rnd, project.team_id)


async def has_conflict(db: AsyncSession, judge_id: str, project_id: str) -> bool:
    return (
        await db.execute(
            select(ConflictDeclaration).where(
                ConflictDeclaration.judge_user_id == judge_id, ConflictDeclaration.project_id == project_id
            )
        )
    ).scalar_one_or_none() is not None


async def scorable_ids(db: AsyncSession, judge_id: str) -> set[str]:
    """Assigned, closed, conflict-free project ids for this judge."""
    assigned = [
        r[0] for r in (await db.execute(select(JudgeAssignment.project_id).where(JudgeAssignment.judge_user_id == judge_id))).all()
    ]
    if not assigned:
        return set()
    conflicts = {
        r[0]
        for r in (await db.execute(select(ConflictDeclaration.project_id).where(ConflictDeclaration.judge_user_id == judge_id))).all()
    }
    out: set[str] = set()
    for project in (await db.execute(select(Project).where(Project.id.in_(assigned)))).scalars().all():
        if project.id in conflicts:
            continue
        if (await project_state(db, project))[1] == "closed":
            out.add(project.id)
    return out
