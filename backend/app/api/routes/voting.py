"""
Community voting.

  * Three access modes, chosen per event: authenticated, email-gated
    (organizer's allowlist), or open link.
  * Two methods: single (one vote per project, up to N projects) or
    quadratic (n votes on a project cost n^2 of a credit budget).
  * The ballot order is shuffled per voter on the SERVER.
  * Results are organizer-only until the organizer publishes them.
  * Rate limits, a DB-level duplicate guard, IP-cluster flags, and a
    voidable, fully audited ballot log.
"""

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.net import request_ip_hash
from app.core.ownership import can_manage, get_event_or_404, get_owned_event
from app.core.security import get_optional_user, require_role
from app.models.event import Event, Track
from app.models.project import Project, SubmissionStatus
from app.models.round import Round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.models.voting import Vote, VoteAllowlist
from app.schemas.voting import (
    AllowlistIn,
    AllowlistOut,
    BallotAdminRow,
    BallotIn,
    BallotOut,
    BallotProject,
    VoteResultRow,
    VotingConfigIn,
    VotingConfigOut,
)
from app.services.audit import audit
from app.services.live import hub
from app.services.ratelimit import limiter
from app.services.results import compute_vote_tally
from app.services.rounds import get_rounds, now_utc
from app.services.voting import (
    email_allowed,
    key_for_email,
    key_for_token,
    key_for_user,
    shuffled,
    validate_allocations,
    voting_state,
)

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))

SHARED_IP_FLAG_THRESHOLD = 4  # this many different voters behind one address => flag for review
VOTE_BURST_PER_IP = (20, 60)   # attempts per window (seconds), per network address
VOTE_BURST_PER_VOTER = (10, 60)
EMAIL_RE = re.compile(r"^(@[^@\s]+\.[^@\s]+|[^@\s]+@[^@\s]+\.[^@\s]+)$")


def _config_out(event: Event) -> VotingConfigOut:
    return VotingConfigOut(
        mode=event.voting_mode, method=event.voting_method, opens_at=event.voting_opens_at,
        closes_at=event.voting_closes_at, max_votes=event.voting_max_votes, credits=event.voting_credits,
        round_id=event.voting_round_id, state=voting_state(event), results_published=event.results_published_at is not None,
    )


async def _ballot_round(db: AsyncSession, event: Event) -> Optional[Round]:
    rounds = await get_rounds(db, event.id)
    if event.voting_round_id:
        return next((r for r in rounds if r.id == event.voting_round_id), None)
    with_work = {
        r[0]
        for r in (
            await db.execute(
                select(Project.round_id).join(Team, Team.id == Project.team_id)
                .where(Team.event_id == event.id, Project.status != SubmissionStatus.DRAFT)
            )
        ).all()
    }
    candidates = [r for r in rounds if r.id in with_work]
    return candidates[-1] if candidates else None


async def _eligible(db: AsyncSession, event: Event, exclude_team_ids: set[str]) -> list[tuple[Project, str, Optional[str]]]:
    rnd = await _ballot_round(db, event)
    if rnd is None:
        return []
    rows = (
        await db.execute(
            select(Project, Team.name, Track.name)
            .join(Team, Team.id == Project.team_id)
            .outerjoin(Track, Track.id == Project.track_id)
            .where(Project.round_id == rnd.id, Project.status != SubmissionStatus.DRAFT)
        )
    ).all()
    return [(p, tn, trk) for p, tn, trk in rows if p.team_id not in exclude_team_ids]


async def _own_team_ids(db: AsyncSession, event: Event, user: Optional[User], email: Optional[str]) -> set[str]:
    """You can't vote for your own team. Known for signed-in voters and for
    email voters whose email matches an account; NOT knowable for
    anonymous open-link voters (documented in THREAT-MODEL.md)."""
    target = user
    if target is None and email:
        target = (await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))).scalar_one_or_none()
    if target is None:
        return set()
    return {
        r[0]
        for r in (
            await db.execute(
                select(Team.id).join(TeamMember, TeamMember.team_id == Team.id)
                .where(TeamMember.user_id == target.id, Team.event_id == event.id)
            )
        ).all()
    }


async def _identify(
    db: AsyncSession, event: Event, user: Optional[User], email: Optional[str], token: Optional[str]
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """((voter_key, kind), None) or (None, reason it isn't possible)."""
    if event.voting_mode == "authenticated":
        return (key_for_user(user.id), None) if user else (None, "Sign in to vote in this event.")
    if event.voting_mode == "email_gated":
        if not email:
            return None, "Enter your email to vote in this event."
        patterns = [r[0] for r in (await db.execute(select(VoteAllowlist.pattern).where(VoteAllowlist.event_id == event.id))).all()]
        if not email_allowed(patterns, email):
            return None, "That email isn't on this event's voter list."
        return key_for_email(email), None
    if event.voting_mode == "open_link":
        return (key_for_token(token), None) if token else (None, "Your browser needs to send a voter token.")
    return None, "Voting isn't enabled for this event."


async def _my_votes(db: AsyncSession, event_id: str, voter_key: str) -> dict[str, int]:
    rows = (
        await db.execute(select(Vote.project_id, Vote.votes).where(Vote.event_id == event_id, Vote.voter_key == voter_key, Vote.voided_at.is_(None)))
    ).all()
    return {pid: v for pid, v in rows}


async def _ballot_out(db, event, user, email, token, seed_hint: str) -> BallotOut:
    ident, reason = await _identify(db, event, user, email, token)
    own = await _own_team_ids(db, event, user, email)
    eligible = await _eligible(db, event, own)
    mine: dict[str, int] = await _my_votes(db, event.id, ident[0]) if ident else {}

    state = voting_state(event)
    if reason is None and state != "open":
        reason = {"off": "Voting isn't enabled for this event.", "not_open": "Voting hasn't opened yet.", "closed": "Voting has closed."}[state]
    if ident and reason is None:
        voided = (
            await db.execute(select(Vote.id).where(Vote.event_id == event.id, Vote.voter_key == ident[0], Vote.voided_at.is_not(None)).limit(1))
        ).first()
        if voided:
            reason = "Your ballot was voided by the organizers."

    by_id = {p.id: (p, tn, trk) for p, tn, trk in eligible}
    order = shuffled(list(by_id), ident[0] if ident else seed_hint)
    used = sum((v if event.voting_method == "single" else v * v) for v in mine.values())
    return BallotOut(
        config=_config_out(event),
        projects=[
            BallotProject(id=pid, title=by_id[pid][0].title, summary=by_id[pid][0].summary, team_name=by_id[pid][1],
                          track_name=by_id[pid][2], tech_stack=by_id[pid][0].tech_stack, repo_url=by_id[pid][0].repo_url,
                          video_url=by_id[pid][0].video_url, my_votes=mine.get(pid, 0))
            for pid in order
        ],
        credits_used=used, can_vote=reason is None, reason=reason,
    )


# ------------------------------- configuration ------------------------------

@router.get("/{event_id}/config", response_model=VotingConfigOut)
async def get_config(event_id: str, db: AsyncSession = Depends(get_db)):
    return _config_out(await get_event_or_404(db, event_id))


@router.put("/{event_id}/config", response_model=VotingConfigOut)
async def set_config(event_id: str, payload: VotingConfigIn, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    if payload.round_id and payload.round_id not in {r.id for r in await get_rounds(db, event_id)}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found for this event.")
    cast = await db.scalar(select(func.count()).select_from(Vote).where(Vote.event_id == event_id))
    if cast and (
        payload.method != event.voting_method
        or (payload.method == "single" and payload.max_votes != event.voting_max_votes)
        or (payload.method == "quadratic" and payload.credits != event.voting_credits)
        or payload.round_id != event.voting_round_id
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ballots have already been cast, so the method, limits and round can't change. You can still change the mode and the window.")

    old = _config_out(event).model_dump(mode="json")
    event.voting_mode = payload.mode
    event.voting_method = payload.method
    event.voting_opens_at = payload.opens_at or (now_utc() if payload.mode != "off" else None)
    event.voting_closes_at = payload.closes_at
    event.voting_max_votes = payload.max_votes
    event.voting_credits = payload.credits
    event.voting_round_id = payload.round_id
    await audit(db, "voting.config", event_id=event_id, actor=organizer, target_type="event", target_id=event_id,
                detail={"from": old, "to": _config_out(event).model_dump(mode="json")})
    await db.commit()
    await hub.publish(event_id, "voting")
    return _config_out(event)


@router.get("/{event_id}/allowlist", response_model=AllowlistOut)
async def get_allowlist(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rows = (await db.execute(select(VoteAllowlist.pattern).where(VoteAllowlist.event_id == event_id).order_by(VoteAllowlist.pattern))).all()
    return AllowlistOut(patterns=[r[0] for r in rows])


@router.put("/{event_id}/allowlist", response_model=AllowlistOut)
async def set_allowlist(event_id: str, payload: AllowlistIn, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """Replace the voter list: exact emails and/or '@domain.com' entries."""
    await get_owned_event(db, event_id, organizer)
    patterns = list(dict.fromkeys(p.strip().lower() for p in payload.patterns if p.strip()))
    bad = [p for p in patterns if not EMAIL_RE.match(p)]
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Not an email or @domain: {', '.join(bad[:5])}")
    await db.execute(delete(VoteAllowlist).where(VoteAllowlist.event_id == event_id))
    for p in patterns:
        db.add(VoteAllowlist(event_id=event_id, pattern=p))
    await audit(db, "voting.allowlist", event_id=event_id, actor=organizer, detail={"entries": len(patterns)})
    await db.commit()
    return AllowlistOut(patterns=sorted(patterns))


# ---------------------------------- ballots ----------------------------------

@router.get("/{event_id}/ballot", response_model=BallotOut)
async def get_ballot(
    event_id: str,
    request: Request,
    email: Optional[str] = Query(default=None, max_length=255),
    voter_token: Optional[str] = Query(default=None, min_length=16, max_length=100),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    """The ballot: eligible projects in a per-voter shuffled order, plus
    this voter's current picks. Never contains anyone's vote counts."""
    event = await get_event_or_404(db, event_id)
    return await _ballot_out(db, event, user, email, voter_token, seed_hint=request.headers.get("x-real-ip", "anon"))


@router.put("/{event_id}/ballot", response_model=BallotOut)
async def put_ballot(
    event_id: str,
    payload: BallotIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_user),
):
    event = await get_event_or_404(db, event_id)
    ip_hash = request_ip_hash(request)

    state = voting_state(event)
    if state != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, {"off": "Voting isn't enabled for this event.", "not_open": "Voting hasn't opened yet.", "closed": "Voting has closed."}[state])

    ident, reason = await _identify(db, event, user, payload.email, payload.voter_token)
    if ident is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED if event.voting_mode == "authenticated" else status.HTTP_403_FORBIDDEN, reason)
    voter_key, kind = ident

    # Rate limits: per network address AND per voter identity.
    if not await limiter.allow(f"vote:ip:{ip_hash}", *VOTE_BURST_PER_IP) or not await limiter.allow(f"vote:voter:{voter_key}", *VOTE_BURST_PER_VOTER):
        await audit(db, "vote.rate_limited", event_id=event_id, actor_label=f"{kind}:{voter_key[2:10]}", ip_hash=ip_hash)
        await db.commit()
        await hub.publish(event_id, "audit")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait a minute and try again.")

    if (await db.execute(select(Vote.id).where(Vote.event_id == event_id, Vote.voter_key == voter_key, Vote.voided_at.is_not(None)).limit(1))).first():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your ballot was voided by the organizers.")

    own = await _own_team_ids(db, event, user, payload.email)
    eligible_ids = {p.id for p, _tn, _t in await _eligible(db, event, own)}
    allocations = {a.project_id: a.votes for a in payload.allocations}
    try:
        cost = validate_allocations(event, allocations, eligible_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    had_ballot = (await db.execute(select(Vote.id).where(Vote.event_id == event_id, Vote.voter_key == voter_key).limit(1))).first() is not None
    await db.execute(delete(Vote).where(Vote.event_id == event_id, Vote.voter_key == voter_key))
    for pid, votes in allocations.items():
        db.add(Vote(event_id=event_id, project_id=pid, voter_key=voter_key, voter_kind=kind, votes=votes,
                    credits_spent=votes if event.voting_method == "single" else votes * votes, ip_hash=ip_hash))
    await db.flush()

    # Duplicate/abuse detection: many DIFFERENT voters behind one address.
    behind = await db.scalar(select(func.count(func.distinct(Vote.voter_key))).where(Vote.event_id == event_id, Vote.ip_hash == ip_hash))
    label = f"{kind}:{voter_key[2:10]}"  # a short reference; never the email or token
    await audit(db, "vote.change" if had_ballot else "vote.cast", event_id=event_id, actor_label=label,
                target_type="ballot", target_id=voter_key,
                detail={"projects": len(allocations), "votes": sum(allocations.values()), "credits": cost}, ip_hash=ip_hash)
    if (behind or 0) >= SHARED_IP_FLAG_THRESHOLD:
        await audit(db, "vote.flagged_shared_ip", event_id=event_id, actor_label=label, target_type="ballot",
                    target_id=voter_key, detail={"voters_behind_this_address": behind}, ip_hash=ip_hash)
    await db.commit()
    await hub.publish(event_id, "ballots", "audit")
    return await _ballot_out(db, event, user, payload.email, payload.voter_token, seed_hint=ip_hash)


# ---------------------------------- results -----------------------------------

@router.get("/{event_id}/results", response_model=list[VoteResultRow])
async def vote_results(event_id: str, db: AsyncSession = Depends(get_db), user: Optional[User] = Depends(get_optional_user)):
    """Hidden from EVERYONE except the event's organizer until published
    (and never while voting is open). Enforced here, at the API."""
    event = await get_event_or_404(db, event_id)
    if not (user and can_manage(event, user)):
        if voting_state(event) == "open":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Results are hidden while voting is open.")
        if event.results_published_at is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Results haven't been published yet.")
    return [VoteResultRow(**r) for r in await compute_vote_tally(db, event_id)]


# ------------------------------- ballot review --------------------------------

@router.get("/{event_id}/ballots", response_model=list[BallotAdminRow])
async def list_ballots(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    """One row per voter for the organizer to review: masked identity,
    how many different voters share the same address, flagged if suspicious."""
    await get_owned_event(db, event_id, organizer)
    votes = (await db.execute(select(Vote).where(Vote.event_id == event_id))).scalars().all()
    ip_voters: dict[str, set[str]] = {}
    for v in votes:
        if v.ip_hash:
            ip_voters.setdefault(v.ip_hash, set()).add(v.voter_key)
    by_voter: dict[str, list[Vote]] = {}
    for v in votes:
        by_voter.setdefault(v.voter_key, []).append(v)
    rows = []
    for key, vs in by_voter.items():
        ip = vs[0].ip_hash
        shared = len(ip_voters.get(ip, ())) if ip else 0
        rows.append(BallotAdminRow(
            voter_ref=key, kind=vs[0].voter_kind, votes=sum(v.votes for v in vs), credits=sum(v.credits_spent for v in vs),
            projects=len(vs), ip_ref=ip[:8] if ip else None, shared_ip_voters=shared,
            flagged=shared >= SHARED_IP_FLAG_THRESHOLD, voided=all(v.voided_at is not None for v in vs),
            updated_at=max(v.updated_at for v in vs),
        ))
    rows.sort(key=lambda r: r.updated_at, reverse=True)
    return rows


async def _set_void(db: AsyncSession, event_id: str, voter_ref: str, organizer: User, void: bool) -> None:
    await get_owned_event(db, event_id, organizer)
    votes = (await db.execute(select(Vote).where(Vote.event_id == event_id, Vote.voter_key == voter_ref))).scalars().all()
    if not votes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No ballot with that reference.")
    for v in votes:
        v.voided_at = now_utc() if void else None
    await audit(db, "ballot.void" if void else "ballot.restore", event_id=event_id, actor=organizer, target_type="ballot", target_id=voter_ref)
    await db.commit()
    await hub.publish(event_id, "ballots", "audit")


@router.post("/{event_id}/ballots/{voter_ref}/void", status_code=status.HTTP_204_NO_CONTENT)
async def void_ballot(event_id: str, voter_ref: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await _set_void(db, event_id, voter_ref, organizer, True)


@router.post("/{event_id}/ballots/{voter_ref}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_ballot(event_id: str, voter_ref: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await _set_void(db, event_id, voter_ref, organizer, False)
