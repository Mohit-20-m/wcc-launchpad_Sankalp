"""Publishing results: the moment judge rankings, winners and community
vote tallies become public. Until then only the event's organizer sees them."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_event_or_404, get_owned_event
from app.core.security import require_role
from app.models.event import Prize
from app.models.round import Round
from app.models.platform_layer import AuditHead
from app.models.user import User, UserRole
from app.models.voting import PrizeAward
from app.schemas.extras import CommunityRow, PublicResultRow, PublicResultsOut, PublishRequest, WinnerOut
from app.services.audit import audit
from app.services.live import hub
from app.services.results import compute_results, compute_vote_tally, resolve_round
from app.services.rounds import now_utc, round_state
from app.services.voting import voting_state

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))


@router.post("/events/{event_id}/publish-results", response_model=PublicResultsOut)
async def publish_results(event_id: str, payload: PublishRequest, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer, with_children=True)
    if voting_state(event) == "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Voting is still open. Close voting (or wait for it to end) before publishing.")
    rnd = await resolve_round(db, event_id, payload.round_id)
    if rnd is None or round_state(rnd) != "closed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Close the round's submissions before publishing its results.")
    ranking = await compute_results(db, event_id, rnd)
    if not ranking:
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no scored projects to publish yet.")

    # Prizes go to ranks in order of prize size (largest first).
    await db.execute(delete(PrizeAward).where(PrizeAward.event_id == event_id))
    prizes = sorted(event.prizes, key=lambda p: (-(float(p.amount) if p.amount is not None else -1), p.name))
    for i, prize in enumerate(prizes[: len(ranking)]):
        db.add(PrizeAward(event_id=event_id, prize_id=prize.id, project_id=ranking[i]["project_id"], rank=i + 1))

    event.results_published_at = now_utc()
    event.results_round_id = rnd.id
    await audit(db, "results.publish", event_id=event_id, actor=organizer, target_type="round", target_id=rnd.id,
                detail={"round": rnd.number, "projects_ranked": len(ranking), "prizes_awarded": min(len(prizes), len(ranking))})
    # Anchor: remember where the tamper-evident audit chain stood at this moment.
    head = (await db.execute(select(AuditHead.seq, AuditHead.last_hash).where(AuditHead.event_key == event_id))).first()
    if head:
        event.results_anchor_seq, event.results_anchor_hash = head
    await db.commit()
    await hub.publish(event_id, "results", "voting", "audit")
    return await _public(db, event_id)


@router.post("/events/{event_id}/unpublish-results", status_code=status.HTTP_204_NO_CONTENT)
async def unpublish_results(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    event.results_published_at = None
    event.results_round_id = None
    await db.execute(delete(PrizeAward).where(PrizeAward.event_id == event_id))
    await audit(db, "results.unpublish", event_id=event_id, actor=organizer, target_type="event", target_id=event_id)
    await db.commit()
    await hub.publish(event_id, "results", "voting", "audit")


async def _public(db: AsyncSession, event_id: str) -> PublicResultsOut:
    event = await get_event_or_404(db, event_id, with_children=True)
    rnd = (await db.execute(select(Round).where(Round.id == event.results_round_id))).scalar_one_or_none()
    ranking = await compute_results(db, event_id, rnd)
    by_id = {r["project_id"]: r for r in ranking}
    prizes = {p.id: p for p in event.prizes}
    awards = (await db.execute(select(PrizeAward).where(PrizeAward.event_id == event_id).order_by(PrizeAward.rank))).scalars().all()
    winners = [
        WinnerOut(prize_name=prizes[a.prize_id].name, amount=float(prizes[a.prize_id].amount) if prizes[a.prize_id].amount is not None else None,
                  rank=a.rank, project_id=a.project_id, project_title=by_id.get(a.project_id, {}).get("project_title", ""),
                  team_name=by_id.get(a.project_id, {}).get("team_name", ""))
        for a in awards if a.prize_id in prizes
    ]
    community = [CommunityRow(**r) for r in await compute_vote_tally(db, event_id)] if event.voting_mode != "off" else []
    return PublicResultsOut(
        event_id=event.id, event_name=event.name, published_at=event.results_published_at, round_name=rnd.name if rnd else "",
        judges_ranking=[
            PublicResultRow(rank=i + 1, project_id=r["project_id"], project_title=r["project_title"], team_name=r["team_name"],
                            normalized_score=r["normalized_score"], raw_average=r["raw_average"])
            for i, r in enumerate(ranking)
        ],
        winners=winners, community=community,
        audit_anchor={"seq": event.results_anchor_seq, "hash": event.results_anchor_hash} if event.results_anchor_hash else None,
    )


@router.get("/events/{event_id}/public-results", response_model=PublicResultsOut)
async def public_results(event_id: str, db: AsyncSession = Depends(get_db)):
    event = await get_event_or_404(db, event_id)
    if event.results_published_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Results haven't been published yet.")
    return await _public(db, event_id)
