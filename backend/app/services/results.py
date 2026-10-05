"""Judge-score results for one round of one event (z-score normalized;
method documented in JUDGING.md). Shared by the organizer's results
route and the publish flow so both always show the same numbers."""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.judging import JudgeAssignment, JudgingCriterion, Score
from app.models.project import Project
from app.models.round import Round
from app.models.team import Team
from app.services.normalization import aggregate_project_scores, weighted_raw_score, zscore_normalize
from app.services.rounds import get_rounds


async def resolve_round(db: AsyncSession, event_id: str, round_id: Optional[str]) -> Optional[Round]:
    rounds = await get_rounds(db, event_id)
    if round_id:
        rnd = next((r for r in rounds if r.id == round_id), None)
        if rnd is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found for this event.")
        return rnd
    if not rounds:
        return None
    with_work = {
        row[0]
        for row in (
            await db.execute(
                select(Project.round_id)
                .join(JudgeAssignment, JudgeAssignment.project_id == Project.id)
                .where(JudgeAssignment.event_id == event_id)
            )
        ).all()
    }
    candidates = [r for r in rounds if r.id in with_work]
    return (candidates or rounds)[-1]


async def compute_results(db: AsyncSession, event_id: str, rnd: Optional[Round]) -> list[dict]:
    crit = await db.execute(select(JudgingCriterion).where(JudgingCriterion.event_id == event_id))
    weights = {c.name: float(c.weight) for c in crit.scalars().all()}

    stmt = select(JudgeAssignment.project_id).where(JudgeAssignment.event_id == event_id)
    if rnd is not None:
        stmt = stmt.join(Project, Project.id == JudgeAssignment.project_id).where(Project.round_id == rnd.id)
    project_ids = {row[0] for row in (await db.execute(stmt)).all()}
    if not project_ids:
        return []

    scores = (await db.execute(select(Score).where(Score.project_id.in_(project_ids)))).scalars().all()
    by_judge: dict[str, list[tuple[str, float]]] = {}
    raw_by_project: dict[str, list[float]] = {}
    for s in scores:
        raw = weighted_raw_score(s.criteria, weights)
        by_judge.setdefault(s.judge_user_id, []).append((s.project_id, raw))
        raw_by_project.setdefault(s.project_id, []).append(raw)

    normalized = aggregate_project_scores(zscore_normalize(by_judge))

    titles = {
        p.id: (p.title, tn)
        for p, tn in (
            await db.execute(
                select(Project, Team.name).join(Team, Team.id == Project.team_id).where(Project.id.in_(project_ids))
            )
        ).all()
    }
    rows = [
        {
            "project_id": pid,
            "project_title": titles.get(pid, ("", ""))[0],
            "team_name": titles.get(pid, ("", ""))[1],
            "judge_count": len(raws),
            "raw_average": sum(raws) / len(raws),
            "normalized_score": normalized.get(pid, 0.0),
        }
        for pid, raws in raw_by_project.items()
    ]
    rows.sort(key=lambda r: r["normalized_score"], reverse=True)
    return rows


async def compute_vote_tally(db: AsyncSession, event_id: str) -> list[dict]:
    """Community vote totals per project (voided ballots excluded).
    Quadratic voting counts VOTES, not credits: a voter who puts 3 votes on
    a project (costing 9 credits) adds 3."""
    from sqlalchemy import func

    from app.models.voting import Vote

    rows = (
        await db.execute(
            select(Vote.project_id, func.sum(Vote.votes), func.count(func.distinct(Vote.voter_key)))
            .where(Vote.event_id == event_id, Vote.voided_at.is_(None))
            .group_by(Vote.project_id)
        )
    ).all()
    if not rows:
        return []
    ids = {r[0] for r in rows}
    info = {
        p.id: (p.title, tn)
        for p, tn in (
            await db.execute(select(Project, Team.name).join(Team, Team.id == Project.team_id).where(Project.id.in_(ids)))
        ).all()
    }
    out = [
        {"project_id": pid, "project_title": info.get(pid, ("", ""))[0], "team_name": info.get(pid, ("", ""))[1],
         "votes": int(total or 0), "voters": int(voters or 0)}
        for pid, total, voters in rows
    ]
    out.sort(key=lambda r: (-r["votes"], r["project_title"]))
    for i, r in enumerate(out, start=1):
        r["rank"] = i
    return out
