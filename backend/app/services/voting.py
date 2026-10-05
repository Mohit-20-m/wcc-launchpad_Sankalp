"""Voting rules: identity, ballot validation, per-voter shuffling."""

import hashlib
import random
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.models.event import Event
from app.services.rounds import aware, now_utc

MODES = ("off", "authenticated", "email_gated", "open_link")
METHODS = ("single", "quadratic")
MAX_VOTES_PER_PROJECT = 20  # quadratic: 20 votes would cost 400 credits


def _h(kind: str, value: str) -> str:
    return hashlib.sha256(f"{settings.jwt_secret}|{kind}|{value}".encode()).hexdigest()[:40]


def key_for_user(user_id: str) -> tuple[str, str]:
    return f"u:{_h('user', user_id)}", "user"


def key_for_email(email: str) -> tuple[str, str]:
    return f"e:{_h('email', email.strip().lower())}", "email"


def key_for_token(token: str) -> tuple[str, str]:
    return f"t:{_h('token', token)}", "token"


def email_allowed(patterns: list[str], email: str) -> bool:
    e = email.strip().lower()
    for p in patterns:
        p = p.strip().lower()
        if p.startswith("@") and e.endswith(p):
            return True
        if p == e:
            return True
    return False


def voting_state(event: Event, now: Optional[datetime] = None) -> str:
    """'off' | 'not_open' | 'open' | 'closed'."""
    now = now or now_utc()
    if event.voting_mode == "off":
        return "off"
    if event.voting_opens_at is not None and now < aware(event.voting_opens_at):
        return "not_open"
    if event.voting_closes_at is not None and now >= aware(event.voting_closes_at):
        return "closed"
    if event.voting_opens_at is None and event.voting_closes_at is None:
        return "closed"  # a window must be set before votes can be cast
    return "open"


def cost_of(method: str, votes: int) -> int:
    return votes if method == "single" else votes * votes


def validate_allocations(event: Event, allocations: dict[str, int], eligible: set[str]) -> int:
    """Return total credits spent, or raise ValueError with a user-facing
    reason. Enforced on the server: the UI is just a convenience."""
    total_cost = 0
    for project_id, votes in allocations.items():
        if project_id not in eligible:
            raise ValueError("One of the projects on your ballot isn't up for voting.")
        if not isinstance(votes, int) or votes < 1:
            raise ValueError("Each vote count must be a whole number of at least 1.")
        if event.voting_method == "single" and votes != 1:
            raise ValueError("In this event each project can receive one vote from you.")
        if votes > MAX_VOTES_PER_PROJECT:
            raise ValueError(f"You can cast at most {MAX_VOTES_PER_PROJECT} votes on one project.")
        total_cost += cost_of(event.voting_method, votes)

    if event.voting_method == "single":
        if len(allocations) > event.voting_max_votes:
            raise ValueError(f"You can vote for at most {event.voting_max_votes} projects.")
    elif total_cost > event.voting_credits:
        raise ValueError(f"That ballot costs {total_cost} credits; you have {event.voting_credits}.")
    return total_cost


def shuffled(project_ids: list[str], seed: str) -> list[str]:
    """A stable per-voter shuffle: the same voter sees the same order on
    every refresh, different voters see different orders, and the server
    controls it (a client can't ask for a favourable order)."""
    ids = sorted(project_ids)
    rng = random.Random(int(hashlib.sha256(f"{settings.jwt_secret}|order|{seed}".encode()).hexdigest(), 16))
    rng.shuffle(ids)
    return ids
