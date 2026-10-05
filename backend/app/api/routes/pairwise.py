"""
Pairwise (head-to-head) judging mode.

Instead of inventing an absolute 1-5 score, a judge is shown two of
their own assigned projects and picks which is better. Many of these
head-to-head results get converted into a single ranking by the
Bradley-Terry estimator in services/bradley_terry.py. This is an
ALTERNATIVE mode alongside the primary rubric scoring,
not a replacement for it -- both exist and can be used independently.
"""

import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.models.judging import JudgeAssignment, PairwiseComparison
from app.models.project import Project
from app.models.team import Team
from app.models.user import User, UserRole
from app.schemas.pairwise import PairwisePair, PairwiseSubmit
from app.services.judging_rules import scorable_ids
from app.services.live import hub

router = APIRouter()


@router.get("/next", response_model=PairwisePair)
async def next_pair(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    # Only projects whose submissions have closed (and that the judge has
    # no conflict on) can be compared -- same rule as scoring.
    project_ids = sorted(await scorable_ids(db, current_user.id))
    if len(project_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You need at least 2 assigned projects with closed submissions to compare.",
        )

    a_id, b_id = random.sample(project_ids, 2)
    result = await db.execute(select(Project).where(Project.id.in_([a_id, b_id])))
    projects = {p.id: p for p in result.scalars().all()}

    return PairwisePair(
        project_a_id=a_id,
        project_a_title=projects[a_id].title,
        project_b_id=b_id,
        project_b_title=projects[b_id].title,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_comparison(
    payload: PairwiseSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.JUDGE)),
):
    # Same integrity rule as regular scoring: a judge can only compare
    # projects they're actually assigned to review -- checked here, at
    # the API, not left to the frontend to enforce.
    result = await db.execute(
        select(JudgeAssignment.project_id).where(
            JudgeAssignment.judge_user_id == current_user.id,
            JudgeAssignment.project_id.in_([payload.project_a_id, payload.project_b_id]),
        )
    )
    assigned_ids = {row[0] for row in result.all()}
    if len(assigned_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be assigned to both projects to compare them.",
        )
    open_ids = await scorable_ids(db, current_user.id)
    if not {payload.project_a_id, payload.project_b_id} <= open_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Comparing opens when submissions for these projects close (and isn't allowed on a conflict).",
        )

    result = await db.execute(select(Project).where(Project.id == payload.project_a_id))
    project_a = result.scalar_one_or_none()
    if project_a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    result = await db.execute(select(Team).where(Team.id == project_a.team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project's team not found.")

    comparison = PairwiseComparison(
        event_id=team.event_id,
        judge_user_id=current_user.id,
        project_a_id=payload.project_a_id,
        project_b_id=payload.project_b_id,
        winner_id=payload.winner_id,
    )
    db.add(comparison)
    await db.commit()
    await hub.publish(team.event_id, "progress")
    return {"status": "recorded"}
