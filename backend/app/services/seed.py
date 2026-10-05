"""
Loads the official fixtures.json into the database (idempotent -- skips
if the fixture event already exists) and ensures four demo accounts
exist with known credentials, printing the demo logins and bootstrap
invite codes on every boot so a fresh install is usable immediately.
"""

import logging
import json
import secrets
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.event import Event, Track
from app.models.invite import RoleInvite
from app.models.judging import JudgeAssignment, Score
from app.models.round import Round
from app.models.project import Project, SubmissionStatus
from app.services.rounds import ensure_default_round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole

logger = logging.getLogger("launchpad.seed")

# Mounted read-only into the container -- see docker-compose.yml's
# backend volumes entry. Single source of truth stays the repo-root
# fixtures.json, never duplicated into the backend build context.
FIXTURES_PATH = Path("/app/fixtures.json")

DEMO_PASSWORD = "DemoPass123!"
# (toml_key, email, display name, role)
# NOTE: uses the .example TLD (RFC 2606, reserved for documentation),
# not .local -- pydantic's EmailStr validator correctly rejects .local
# as a special-use/reserved name, which silently broke login until this
# was caught by an actual end-to-end test, not just an import check.
DEMO_ACCOUNTS = [
    ("organizer", "organizer@launchpad.example", "Demo Organizer", UserRole.ORGANIZER),
    ("judge_a", "judge_a@launchpad.example", "Demo Judge A", UserRole.JUDGE),
    ("judge_b", "judge_b@launchpad.example", "Demo Judge B", UserRole.JUDGE),
    ("participant", "participant@launchpad.example", "Demo Participant", UserRole.PARTICIPANT),
]

# Shared password for the ~100 placeholder accounts created for fixture
# team members -- these are historical seed data, not meant to be
# anyone's real login, so one known password is fine and documented.
FIXTURE_MEMBER_PASSWORD = "fixture-demo-pass"
FIXTURE_JUDGE_PASSWORD = "fixture-judge-pass"


def _parse_iso(value: str) -> datetime:
    # Python 3.11+ handles the trailing 'Z' directly.
    return datetime.fromisoformat(value)


async def _get_or_create_user(
    db: AsyncSession, email: str, name: str, role: UserRole, password: str
) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, name=name, role=role, password_hash=hash_password(password))
        db.add(user)
        await db.flush()
    return user


async def _seed_fixture_event(db: AsyncSession, fixture: dict, organizer: User) -> None:
    event_id = fixture["event"]["id"]
    result = await db.execute(select(Event).where(Event.id == event_id))
    if result.scalar_one_or_none() is not None:
        logger.info("Fixture event %s already seeded, skipping.", event_id)
        return

    closes = _parse_iso(fixture["event"]["submissions_close"])
    db.add(Event(
        id=event_id,
        name=fixture["event"]["name"],
        submissions_close=closes,
        owner_id=organizer.id,  # the demo organizer owns the fixture event
    ))
    # Every event has at least one round; the fixture event's single
    # round closed on the fixture's own (past) deadline.
    # closed_notified_at: this round closed long ago (historical seed data),
    # so the deadline sweeper must not announce it -- that would queue
    # "scoring is open" emails and webhooks for every fixture judge on boot.
    fixture_round = Round(id="rnd_01", event_id=event_id, number=1, name="Round 1", closes_at=closes, closed_notified_at=closes)
    db.add(fixture_round)

    for t in fixture["tracks"]:
        db.add(Track(id=t["id"], event_id=event_id, name=t["name"]))

    # One placeholder User per unique team-member email in the fixture,
    # so TeamMember rows (which have a real foreign key to users.id)
    # have something real to reference.
    member_emails = {m for team in fixture["teams"] for m in team["members"]}
    email_to_user: dict[str, User] = {}
    for email in member_emails:
        email_to_user[email] = await _get_or_create_user(
            db, email, email.split("@")[0], UserRole.PARTICIPANT, FIXTURE_MEMBER_PASSWORD
        )
    await db.flush()

    for team in fixture["teams"]:
        # Reusing the fixture's own team id as the invite code: these are
        # historical seeded teams, not ones anyone needs to actually
        # invite people into, so a random code would add nothing.
        db.add(Team(id=team["id"], event_id=event_id, name=team["name"], invite_code=team["id"]))
    await db.flush()

    for i, team in enumerate(fixture["teams"]):
        for j, email in enumerate(team["members"]):
            db.add(TeamMember(
                team_id=team["id"],
                user_id=email_to_user[email].id,
                is_leader=(j == 0),
            ))

    for project in fixture["projects"]:
        submitted_at = _parse_iso(project["submitted_at"])
        db.add(Project(
            id=project["id"],
            team_id=project["team"],
            round_id=fixture_round.id,
            track_id=project["track"],
            title=project["title"],
            summary=project.get("summary"),
            repo_url=project.get("repo_url"),
            status=SubmissionStatus.SUBMITTED,
            submitted_at=submitted_at,
            updated_at=submitted_at,
        ))
    await db.flush()

    # Real fixture judges (jdg_01..jdg_30) as actual Users, so their
    # scores below have a real foreign key to reference. Not the same
    # accounts as our four demo organizer/judge_a/judge_b/participant
    # logins -- those exist so judges and testers have known, stable
    # credentials to try every role with.
    judge_id_to_user: dict[str, User] = {}
    for j in fixture["judges"]:
        judge_id_to_user[j["id"]] = await _get_or_create_user(
            db, j["email"], j["name"], UserRole.JUDGE, FIXTURE_JUDGE_PASSWORD
        )
    await db.flush()

    # The fixture's scores array -- includes deliberately awkward cases
    # (a judge who scored everything the same, projects with anywhere
    # from 0 to 5 reviews). Each score implies an assignment existed,
    # so we create both together.
    for s in fixture["scores"]:
        judge_user = judge_id_to_user[s["judge"]]
        db.add(JudgeAssignment(event_id=event_id, judge_user_id=judge_user.id, project_id=s["project"]))
        db.add(Score(
            judge_user_id=judge_user.id,
            project_id=s["project"],
            criteria=s["criteria"],
            comment=s.get("comment") or None,
        ))
    await db.flush()

    # Give our two demo judge accounts a few real assignments too, so
    # there's something to actually score through the UI/API when
    # testing or recording the demo video, so the seeded state is
    # genuinely usable end to end.
    demo_judge_a = await _get_or_create_user(
        db, "judge_a@launchpad.example", "Demo Judge A", UserRole.JUDGE, DEMO_PASSWORD
    )
    demo_judge_b = await _get_or_create_user(
        db, "judge_b@launchpad.example", "Demo Judge B", UserRole.JUDGE, DEMO_PASSWORD
    )
    sample_project_ids = [p["id"] for p in fixture["projects"][:3]]
    for demo_judge in (demo_judge_a, demo_judge_b):
        for project_id in sample_project_ids:
            db.add(JudgeAssignment(event_id=event_id, judge_user_id=demo_judge.id, project_id=project_id))

    await db.commit()
    logger.info(
        "Seeded fixture event: %d tracks, %d teams, %d projects.",
        len(fixture["tracks"]), len(fixture["teams"]), len(fixture["projects"]),
    )


async def _seed_expertise(db: AsyncSession, fixture: dict) -> None:
    """Fixture judges list the tracks they know; auto-assignment uses that.
    Runs on every boot but only fills in what's missing (idempotent), so an
    existing database picks it up without a wipe."""
    from app.models.engage import JudgeExpertise

    event_id = fixture["event"]["id"]
    if (await db.execute(select(JudgeExpertise.id).where(JudgeExpertise.event_id == event_id).limit(1))).first():
        return
    valid_tracks = {t["id"] for t in fixture["tracks"]}
    for j in fixture["judges"]:
        user = (await db.execute(select(User).where(User.email == j["email"]))).scalar_one_or_none()
        if user is None:
            continue
        for t in j.get("tracks", []):
            if t in valid_tracks:
                db.add(JudgeExpertise(event_id=event_id, judge_user_id=user.id, track_id=t))
    await db.commit()


async def _repair(db: AsyncSession) -> None:
    """Idempotent tidy-up so every event has a round and every project
    belongs to one (covers events/projects created before rounds existed)."""
    for event in (await db.execute(select(Event))).scalars().all():
        rnd = await ensure_default_round(db, event)
        for project in (
            await db.execute(
                select(Project).join(Team, Team.id == Project.team_id).where(Team.event_id == event.id, Project.round_id.is_(None))
            )
        ).scalars().all():
            project.round_id = rnd.id
    await db.commit()


async def _bootstrap_invites(db: AsyncSession) -> list[tuple[str, str]]:
    """One long-lived invite per privileged role, so a fresh deployment
    can onboard its first organizer/judges without touching the database.
    The codes are printed on every boot, next to the demo accounts."""
    out = []
    for role in (UserRole.ORGANIZER, UserRole.JUDGE):
        invite = (
            await db.execute(select(RoleInvite).where(RoleInvite.role == role, RoleInvite.label == "bootstrap"))
        ).scalar_one_or_none()
        if invite is None:
            invite = RoleInvite(code=secrets.token_urlsafe(9), role=role, label="bootstrap", max_uses=1000)
            db.add(invite)
            await db.commit()
        out.append((role.value, invite.code))
    return out


async def run_seed(db: AsyncSession) -> None:
    # Demo accounts first: the organizer owns the fixture event.
    accounts: dict[str, User] = {}
    for key, email, name, role in DEMO_ACCOUNTS:
        accounts[key] = await _get_or_create_user(db, email, name, role, DEMO_PASSWORD)
        await db.commit()

    if FIXTURES_PATH.exists():
        fixture = json.loads(FIXTURES_PATH.read_text())
        await _seed_fixture_event(db, fixture, accounts["organizer"])
        await _seed_expertise(db, fixture)
    else:
        logger.warning("fixtures.json not found at %s -- skipping fixture seed.", FIXTURES_PATH)

    await _repair(db)
    invites = await _bootstrap_invites(db)

    account_lines = [f"  {role.value:<12} {email}" for _key, email, _name, role in DEMO_ACCOUNTS]

    banner = (
        "\n" + "=" * 78 + "\n"
        "WCC Launchpad demo accounts (all share the password: " + DEMO_PASSWORD + ")\n"
        + "\n".join(account_lines) + "\n"
        + "-" * 78 + "\n"
        "Invite codes (needed to self-register as these roles):\n"
        + "\n".join(f"  {role:<12} {code}" for role, code in invites) + "\n"
        + "=" * 78 + "\n"
    )
    # flush=True: stdout is block-buffered when it is a pipe (as in `docker
    # compose logs`), so without it the banner can sit unseen in a buffer.
    print(banner, flush=True)
