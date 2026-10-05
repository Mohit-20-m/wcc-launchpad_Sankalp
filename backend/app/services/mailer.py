"""Email notifications.

Same design as webhooks (services/webhooks.py):

* An email is written to `email_outbox` IN THE SAME TRANSACTION as the
  action that caused it (a transactional outbox), so nobody is told about
  something that rolled back, and nothing is lost if the mail server is down.
* Most emails are triggered from the audit trail: `audit()` calls
  `enqueue_for_action`, so "what gets emailed" hangs off "what gets audited".
* A background loop sends due emails with retries and backoff, and sweeps for
  teams that still haven't submitted as a deadline approaches.
* Delivery goes through the SendGrid HTTP API or any SMTP server. If the
  provider is down the platform keeps working; emails wait and retry. If no
  provider is configured yet, emails are recorded as skipped (and can be
  retried later from the outbox) rather than failing repeatedly.
* Demo and fixture accounts use reserved domains (RFC 2606 / RFC 6761) that
  are ALWAYS skipped, so seeding and demo activity never email anyone.

People stay in control: reminders and general updates respect a per-user
preference and a per-event switch. Emails someone needs in order to act
(team invites, judge assignments, certificates) are always sent.
"""
import asyncio
import html
import logging
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Iterable, Optional

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.engage import EmailOutbox, MailPreference, MailSettings

log = logging.getLogger("launchpad.mail")
# Always visible in `docker compose logs backend`, whatever the root logger does.
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("MAIL %(levelname)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False

# Categories decide whether preferences apply.
ESSENTIAL = "essential"   # always sent (unless the event switched email off entirely)
UPDATE = "update"         # e.g. "results are out" -- user can opt out
REMINDER = "reminder"     # deadline nudges -- user and event can opt out

KIND_CATEGORY = {
    "team_created": UPDATE,
    "team_joined": UPDATE,
    "team_invite": ESSENTIAL,
    "submission_receipt": ESSENTIAL,
    "judge_assigned": ESSENTIAL,
    "judge_assigned_batch": ESSENTIAL,
    "judge_invite": ESSENTIAL,
    "scoring_open": ESSENTIAL,
    "extension_granted": ESSENTIAL,
    "deadline_reminder": REMINDER,
    "results_published": UPDATE,
    "certificate": ESSENTIAL,
    "welcome": ESSENTIAL,
    "test": ESSENTIAL,
}

# Reserved for documentation/testing: mail to these can never be delivered,
# and the seed data's demo and fixture accounts all live on them.
RESERVED_DOMAINS = {"example.org", "example.com", "example.net", "launchpad.example"}
RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost", ".local")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def base_url() -> str:
    return (settings.public_base_url or "http://localhost:8080").rstrip("/")


def _fmt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%a %d %b %Y, %H:%M UTC")


def render(heading: str, paragraphs: list[str], cta: Optional[tuple[str, str]] = None, footer: Optional[str] = None) -> tuple[str, str]:
    """(text, html). Paragraphs are plain text; everything is escaped."""
    name = settings.platform_name
    text_parts = [heading, "", *paragraphs]
    if cta:
        text_parts += ["", f"{cta[0]}: {cta[1]}"]
    foot = footer or f"You're receiving this because of your activity on {name}. You can turn off reminders and updates in your console."
    text_parts += ["", "--", foot]
    text = "\n".join(text_parts)

    ps = "".join(f'<p style="margin:0 0 14px;line-height:1.55">{html.escape(p)}</p>' for p in paragraphs)
    button = ""
    if cta:
        button = (f'<p style="margin:22px 0"><a href="{html.escape(cta[1], quote=True)}" '
                  f'style="background:#111;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">'
                  f'{html.escape(cta[0])}</a></p>')
    body = (
        '<div style="background:#f4f4f5;padding:28px 12px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;padding:28px;border:1px solid #e4e4e7">'
        f'<div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#71717a;margin-bottom:10px">{html.escape(name)}</div>'
        f'<h1 style="font-size:20px;margin:0 0 16px">{html.escape(heading)}</h1>{ps}{button}'
        f'<p style="margin:22px 0 0;font-size:12px;color:#71717a;line-height:1.5">{html.escape(foot)}</p>'
        '</div></div>'
    )
    return text, body


# --------------------------------------------------------------------------- #
# Queueing
# --------------------------------------------------------------------------- #

async def event_settings(db: AsyncSession, event_id: Optional[str]) -> MailSettings:
    if event_id:
        row = (await db.execute(select(MailSettings).where(MailSettings.event_id == event_id))).scalar_one_or_none()
        if row is not None:
            return row
    return MailSettings(event_id=event_id or "", enabled=True, reminders_enabled=True, reminder_hours="24,3", certificate_emails=True)


async def user_prefs(db: AsyncSession, user_id: Optional[str]) -> MailPreference:
    if user_id:
        row = (await db.execute(select(MailPreference).where(MailPreference.user_id == user_id))).scalar_one_or_none()
        if row is not None:
            return row
    return MailPreference(user_id=user_id or "", reminders=True, updates=True)


def skip_domains() -> set[str]:
    extra = {d.strip().lower() for d in settings.mail_skip_domains.split(",") if d.strip()}
    return RESERVED_DOMAINS | extra


def is_skipped_domain(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower().strip()
    return domain in skip_domains() or domain.endswith(RESERVED_TLDS) or any(domain.endswith("." + d) for d in RESERVED_DOMAINS)


def not_configured_reason() -> Optional[str]:
    """None when sending is set up, else why not."""
    provider = settings.mail_provider.lower()
    if provider == "disabled":
        return "Email sending is disabled (MAIL_PROVIDER=disabled)."
    if provider == "sendgrid":
        return None if settings.sendgrid_api_key.strip() else "SENDGRID_API_KEY isn't set."
    if provider == "smtp":
        return None if settings.smtp_host.strip() else "SMTP_HOST isn't set."
    return f"Unknown MAIL_PROVIDER '{settings.mail_provider}' (use sendgrid, smtp or disabled)."


async def queue(
    db: AsyncSession,
    *,
    to_email: str,
    kind: str,
    subject: str,
    text: str,
    html_body: str,
    event_id: Optional[str] = None,
    user_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    attachment_ref: Optional[str] = None,
) -> bool:
    """Add one email to the caller's transaction. Returns True only when it
    will actually be sent (False: opted out, event switched off, already
    queued, demo address, or email not configured -- the last two are still
    recorded in the outbox as skipped)."""
    category = KIND_CATEGORY.get(kind, UPDATE)
    ev = await event_settings(db, event_id)
    if not ev.enabled and kind != "test":
        return False
    if category == REMINDER and not ev.reminders_enabled:
        return False
    if category != ESSENTIAL:
        prefs = await user_prefs(db, user_id)
        if (category == REMINDER and not prefs.reminders) or (category == UPDATE and not prefs.updates):
            return False
    if dedupe_key:
        if (await db.execute(select(EmailOutbox.id).where(EmailOutbox.dedupe_key == dedupe_key))).first():
            return False
    status, error = "pending", None
    if is_skipped_domain(to_email):
        status, error = "skipped", "Demo/reserved address; never emailed."
    elif (reason := not_configured_reason()):
        status, error = "skipped", f"Not sent: {reason} Configure email, then press Retry."
    row = EmailOutbox(
        event_id=event_id, user_id=user_id, to_email=to_email, kind=kind, subject=subject[:300],
        body_text=text, body_html=html_body, attachment_ref=attachment_ref, dedupe_key=dedupe_key,
        status=status, error=error, next_attempt_at=datetime.now(timezone.utc),
    )
    if dedupe_key:
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            return False  # another worker queued the same email first
    else:
        db.add(row)
    # True only if it will actually be sent, so "emailed N people" counts are honest.
    return status == "pending"


# --------------------------------------------------------------------------- #
# Who gets told what, driven by the audit trail
# --------------------------------------------------------------------------- #

async def _team_members(db: AsyncSession, team_id: str):
    from app.models.team import TeamMember
    from app.models.user import User

    return (await db.execute(select(User).join(TeamMember, TeamMember.user_id == User.id).where(TeamMember.team_id == team_id))).scalars().all()


async def enqueue_for_action(db: AsyncSession, event_id: str, action: str, target_type, target_id, detail: Optional[dict], actor) -> None:
    """Called by audit() for every audited action. Cheap no-op for actions
    that don't email anyone."""
    handler = _HANDLERS.get(action)
    if handler is None:
        return
    try:
        async with db.begin_nested():
            await handler(db, event_id, target_id, detail or {}, actor)
    except Exception:  # noqa: BLE001 -- an email problem must never fail the user's action
        log.exception("could not queue email for %s", action)


async def _event(db: AsyncSession, event_id: str):
    from app.models.event import Event

    return (await db.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()


async def _on_team_create(db, event_id, team_id, detail, actor):
    from app.models.team import Team

    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    ev = await _event(db, event_id)
    if team is None or ev is None or actor is None:
        return
    text, body = render(
        f"Team {team.name} is ready",
        [f"You created {team.name} for {ev.name}.",
         f"Your team code is {team.invite_code}. Teammates enter it on the Squad tab to join, or you can invite them by email from there.",
         "Teams can have up to 4 members."],
        ("Open your console", f"{base_url()}/participant?tab=squad"),
    )
    await queue(db, to_email=actor.email, user_id=actor.id, event_id=event_id, kind="team_created",
                subject=f"Team {team.name} created — code {team.invite_code}", text=text, html_body=body)


async def _on_team_join(db, event_id, team_id, detail, actor):
    from app.models.team import Team

    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None or actor is None:
        return
    for m in await _team_members(db, team_id):
        if m.id == actor.id:
            continue
        text, body = render(f"{actor.name} joined {team.name}", [f"{actor.name} ({actor.email}) just joined your team."],
                            ("See your team", f"{base_url()}/participant?tab=squad"))
        await queue(db, to_email=m.email, user_id=m.id, event_id=event_id, kind="team_joined",
                    subject=f"{actor.name} joined {team.name}", text=text, html_body=body)


async def _on_submission(db, event_id, project_id, detail, actor):
    from app.models.project import Project
    from app.models.round import Round
    from app.models.team import Team
    from app.services.rounds import get_extension

    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p is None:
        return
    team = (await db.execute(select(Team).where(Team.id == p.team_id))).scalar_one_or_none()
    rnd = (await db.execute(select(Round).where(Round.id == p.round_id))).scalar_one_or_none() if p.round_id else None
    if team is None:
        return
    closes = rnd.closes_at if rnd else None
    if rnd:
        ext = await get_extension(db, rnd.id, team.id)
        if ext:
            closes = ext.closes_at
    who = f" by {actor.name}" if actor else ""
    lines = [f"\u201c{p.title}\u201d was submitted{who} for {team.name}" + (f" in {rnd.name}." if rnd else "."),
             f"Received: {_fmt(p.submitted_at or datetime.now(timezone.utc))}."]
    if closes:
        lines.append(f"You can keep editing until {_fmt(closes)}. After that, the version on file is what judges see.")
    if p.repo_url:
        lines.append(f"Repository on file: {p.repo_url}")
    stamp = int((p.submitted_at or datetime.now(timezone.utc)).timestamp())
    for m in await _team_members(db, team.id):
        text, body = render("Submission received", lines, ("Review your submission", f"{base_url()}/participant?tab=build"))
        await queue(db, to_email=m.email, user_id=m.id, event_id=event_id, kind="submission_receipt",
                    subject=f"Received: {p.title}", text=text, html_body=body, dedupe_key=f"receipt:{p.id}:{stamp}:{m.id}")


async def _on_judge_assign(db, event_id, project_id, detail, actor):
    from app.models.user import User

    email = detail.get("judge")
    if not email:
        return
    judge = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    ev = await _event(db, event_id)
    if judge is None or ev is None:
        return
    text, body = render(
        "You have a project to review",
        [f"You've been assigned to review \u201c{detail.get('project', 'a project')}\u201d at {ev.name}.",
         "You can read the submission now. Scoring opens when the round's submissions close, so you never score work that can still change.",
         "If you know the team, declare a conflict of interest from your queue before scoring."],
        ("Open your judging queue", f"{base_url()}/judge"),
    )
    await queue(db, to_email=judge.email, user_id=judge.id, event_id=event_id, kind="judge_assigned",
                subject=f"Review assigned: {detail.get('project', 'a project')}", text=text, html_body=body)


async def _on_round_closed(db, event_id, round_id, detail, actor):
    """Scoring opens when submissions close: tell the judges who have work."""
    from app.models.judging import JudgeAssignment
    from app.models.project import Project
    from app.models.round import Round
    from app.models.user import User

    rnd = (await db.execute(select(Round).where(Round.id == round_id))).scalar_one_or_none()
    ev = await _event(db, event_id)
    if rnd is None or ev is None:
        return
    rows = (await db.execute(
        select(User, JudgeAssignment.project_id).join(JudgeAssignment, JudgeAssignment.judge_user_id == User.id)
        .join(Project, Project.id == JudgeAssignment.project_id).where(Project.round_id == rnd.id)
    )).all()
    counts: dict[str, tuple] = {}
    for u, _pid in rows:
        counts[u.id] = (u, counts.get(u.id, (u, 0))[1] + 1)
    for u, n in counts.values():
        text, body = render(f"Scoring is open for {rnd.name}",
                            [f"Submissions for {rnd.name} at {ev.name} have closed, so the work is final.",
                             f"You have {n} project(s) to score."],
                            ("Start scoring", f"{base_url()}/judge"))
        await queue(db, to_email=u.email, user_id=u.id, event_id=event_id, kind="scoring_open",
                    subject=f"Scoring is open: {rnd.name} ({n} to review)", text=text, html_body=body,
                    dedupe_key=f"scoring_open:{rnd.id}:{u.id}:{int((rnd.closed_early_at or rnd.closes_at).timestamp())}")


async def _on_extension(db, event_id, team_id, detail, actor):
    from app.models.round import Round, TeamExtension

    rnd = (await db.execute(select(Round).where(Round.event_id == event_id, Round.number == detail.get("round")))).scalar_one_or_none()
    if rnd is None or not team_id:
        return
    ext = (await db.execute(select(TeamExtension).where(TeamExtension.round_id == rnd.id, TeamExtension.team_id == team_id))).scalar_one_or_none()
    if ext is None:
        return
    for m in await _team_members(db, team_id):
        text, body = render("You've been given more time",
                            [f"The organizers extended your team's deadline for {rnd.name} to {_fmt(ext.closes_at)}."]
                            + ([f"Reason: {ext.reason}"] if ext.reason else []),
                            ("Open your build", f"{base_url()}/participant?tab=build"))
        await queue(db, to_email=m.email, user_id=m.id, event_id=event_id, kind="extension_granted",
                    subject=f"Extension granted: {rnd.name}", text=text, html_body=body)


async def _on_results(db, event_id, round_id, detail, actor):
    from app.models.judging import JudgeAssignment
    from app.models.team import Team, TeamMember
    from app.models.user import User

    ev = await _event(db, event_id)
    if ev is None:
        return
    people: dict[str, User] = {}
    for u in (await db.execute(select(User).join(TeamMember, TeamMember.user_id == User.id).join(Team, Team.id == TeamMember.team_id)
                               .where(Team.event_id == event_id))).scalars().all():
        people[u.id] = u
    for u in (await db.execute(select(User).join(JudgeAssignment, JudgeAssignment.judge_user_id == User.id)
                               .where(JudgeAssignment.event_id == event_id))).scalars().all():
        people[u.id] = u
    stamp = int((ev.results_published_at or datetime.now(timezone.utc)).timestamp())
    for u in people.values():
        text, body = render(f"Results are out for {ev.name}",
                            ["The organizers have published the results. Rankings, winners and the community vote are now public.",
                             "Certificates, if the organizers issue them, will arrive in a separate email."],
                            ("See the results", f"{base_url()}/results/{ev.id}"))
        await queue(db, to_email=u.email, user_id=u.id, event_id=event_id, kind="results_published",
                    subject=f"Results are out: {ev.name}", text=text, html_body=body, dedupe_key=f"results:{ev.id}:{stamp}:{u.id}")


_HANDLERS = {
    "team.create": _on_team_create,
    "team.join": _on_team_join,
    "submission.create": _on_submission,
    "submission.replace": _on_submission,
    "judge.assign": _on_judge_assign,
    "round.close_early": _on_round_closed,
    "round.deadline_passed": _on_round_closed,
    "round.extend_team": _on_extension,
    "results.publish": _on_results,
}


# --------------------------------------------------------------------------- #
# Emails sent directly by routes (not from an audit action)
# --------------------------------------------------------------------------- #

async def queue_welcome(db: AsyncSession, user, event_name: Optional[str] = None) -> bool:
    """Sent once when someone registers. Never for seeded demo accounts:
    seeding doesn't call this, and their domains are always skipped anyway."""
    role = getattr(user.role, "value", str(user.role))
    name = settings.platform_name
    if role == "judge":
        lines = [f"Your judge account on {name} is ready" + (f" for {event_name}." if event_name else "."),
                 "You'll get an email whenever projects are assigned to you, and again when scoring opens.",
                 "You can read a submission as soon as it's assigned; scoring opens once the round's submissions close."]
        cta = ("Open your judging queue", f"{base_url()}/judge")
    elif role == "organizer":
        lines = [f"Your organizer account on {name} is ready.",
                 "Create your event, add tracks, prizes and rounds, then invite judges by email from the Judging panel.",
                 "Teams get receipts and deadline reminders automatically; you can see every email in the Notifications tab."]
        cta = ("Open the organizer console", f"{base_url()}/organizer")
    else:
        lines = [f"Welcome to {name}, {user.name}!",
                 "Next step: create a squad or join one with a code your teammate shares (teams of 1-4).",
                 "You'll get a receipt every time your team submits, and a reminder if the deadline is close and you haven't submitted yet."]
        cta = ("Find or create your squad", f"{base_url()}/participant?tab=squad")
    text, body = render(f"Welcome, {user.name}", lines, cta,
                        footer=f"You're receiving this because an account was created on {name} with this address. If that wasn't you, you can ignore this email.")
    return await queue(db, to_email=user.email, user_id=user.id, kind="welcome", subject=f"Welcome to {name}",
                       text=text, html_body=body, dedupe_key=f"welcome:{user.id}")


async def queue_team_invites(db: AsyncSession, team, event, inviter, emails: Iterable[str], note: Optional[str]) -> int:
    n = 0
    for email in emails:
        lines = [f"{inviter.name} invited you to join {team.name} at {event.name}.",
                 f"Your team code is {team.invite_code}.",
                 "Sign in (or create a participant account), open the Squad tab and enter the code."]
        if note:
            lines.insert(1, f"Their note: {note}")
        text, body = render(f"Join {team.name}", lines, ("Join the team", f"{base_url()}/participant?tab=squad&code={team.invite_code}"))
        if await queue(db, to_email=email, event_id=event.id, kind="team_invite", subject=f"{inviter.name} invited you to {team.name}",
                       text=text, html_body=body, dedupe_key=f"team_invite:{team.id}:{email.lower()}:{datetime.now(timezone.utc):%Y%m%d%H}"):
            n += 1
    return n


async def queue_judge_invites(db: AsyncSession, invite, event_name: str, inviter, emails: Iterable[str]) -> int:
    n = 0
    for email in emails:
        text, body = render("You're invited to judge",
                            [f"{inviter.name} invited you to judge {event_name}.",
                             f"Your judge invite code is {invite.code}.",
                             "Create your judge account on the sign-up page and enter the code. You'll get an email when projects are assigned to you."],
                            ("Create your judge account", f"{base_url()}/register?role=judge&code={invite.code}"))
        if await queue(db, to_email=email, event_id=invite.event_id, kind="judge_invite", subject=f"Invitation to judge {event_name}",
                       text=text, html_body=body, dedupe_key=f"judge_invite:{invite.id}:{email.lower()}"):
            n += 1
    return n


async def queue_assignment_batch(db: AsyncSession, event, per_judge: dict) -> int:
    """One email per judge after auto-assignment, not one per project."""
    n = 0
    for judge, titles in per_judge.values():
        shown = titles[:8]
        more = len(titles) - len(shown)
        text, body = render(
            f"You have {len(titles)} project(s) to review",
            [f"You've been assigned {len(titles)} project(s) at {event.name}:", " • " + "\n • ".join(shown) + (f"\n …and {more} more" if more else ""),
             "Scoring opens when each round's submissions close. If you know a team, declare a conflict of interest from your queue before scoring."],
            ("Open your judging queue", f"{base_url()}/judge"),
        )
        if await queue(db, to_email=judge.email, user_id=judge.id, event_id=event.id, kind="judge_assigned_batch",
                       subject=f"{len(titles)} project(s) assigned to you at {event.name}", text=text, html_body=body):
            n += 1
    return n


async def queue_certificate(db: AsyncSession, cert, event_name: str, email: str, force: bool = False) -> bool:
    headline = {"winner": f"You won {cert.title}", "judge": "Thank you for judging", "participation": "Your certificate of participation"}.get(cert.kind, "Your certificate")
    text, body = render(
        headline,
        [f"Your certificate for {event_name} is attached as a PDF.",
         f"Anyone can confirm it's genuine with the code {cert.code}: the verification page shows who it was issued to and whether it is still valid."],
        ("Verify this certificate", f"{base_url()}/verify/{cert.code}"),
    )
    key = None if force else f"certificate:{cert.id}"
    return await queue(db, to_email=email, user_id=cert.user_id, event_id=cert.event_id, kind="certificate",
                       subject=f"{headline} — {event_name}", text=text, html_body=body, attachment_ref=f"certificate:{cert.id}", dedupe_key=key)


# --------------------------------------------------------------------------- #
# Deadline reminders: only to teams that haven't submitted
# --------------------------------------------------------------------------- #

def _hours(spec: str) -> list[float]:
    out = []
    for x in spec.split(","):
        try:
            v = float(x)
        except ValueError:
            continue
        if 0 < v <= 24 * 14:
            out.append(v)
    return sorted(set(out), reverse=True)


async def sweep_reminders(now: Optional[datetime] = None) -> int:
    """For every open round, find teams with no submission whose deadline
    (their own, if extended) falls inside a reminder window, and queue one
    reminder per window per person. Idempotent via dedupe keys."""
    from app.models.event import Event
    from app.models.project import Project, SubmissionStatus
    from app.models.round import Round, RoundAdvancement, TeamExtension
    from app.models.team import Team
    from app.services.rounds import aware

    now = now or datetime.now(timezone.utc)
    queued = 0
    async with AsyncSessionLocal() as db:
        rounds = (await db.execute(select(Round).where(Round.closed_early_at.is_(None)))).scalars().all()
        for rnd in rounds:
            if rnd.opens_at is not None and aware(rnd.opens_at) > now:
                continue
            ev_settings = await event_settings(db, rnd.event_id)
            if not ev_settings.enabled or not ev_settings.reminders_enabled:
                continue
            windows = _hours(ev_settings.reminder_hours)
            if not windows:
                continue
            ev = (await db.execute(select(Event).where(Event.id == rnd.event_id))).scalar_one_or_none()
            if ev is None:
                continue
            teams = (await db.execute(select(Team).where(Team.event_id == rnd.event_id))).scalars().all()
            if not rnd.open_to_all:
                allowed = {r[0] for r in (await db.execute(select(RoundAdvancement.team_id).where(RoundAdvancement.round_id == rnd.id))).all()}
                teams = [t for t in teams if t.id in allowed]
            if not teams:
                continue
            submitted = {r[0] for r in (await db.execute(
                select(Project.team_id).where(Project.round_id == rnd.id, Project.status != SubmissionStatus.DRAFT))).all()}
            drafts = {r[0] for r in (await db.execute(
                select(Project.team_id).where(Project.round_id == rnd.id, Project.status == SubmissionStatus.DRAFT))).all()}
            exts = {e.team_id: e.closes_at for e in (await db.execute(select(TeamExtension).where(TeamExtension.round_id == rnd.id))).scalars().all()}
            for team in teams:
                if team.id in submitted:
                    continue
                deadline = aware(exts.get(team.id) or rnd.closes_at)
                left = (deadline - now).total_seconds() / 3600
                if left <= 0:
                    continue
                # The tightest window we're inside (e.g. 3h beats 24h).
                inside = [w for w in windows if left <= w]
                if not inside:
                    continue
                window = min(inside)
                hrs = max(1, round(left))
                when = f"about {hrs} hour{'s' if hrs != 1 else ''}" if left >= 1 else "less than an hour"
                lines = [f"{team.name} hasn't submitted for {rnd.name} at {ev.name} yet.",
                         f"The deadline is {_fmt(deadline)} — {when} from now."]
                if team.id in drafts:
                    lines.append("You have a draft saved. Submitting it takes one click.")
                lines.append("Submitting early is safe: you can keep editing until the deadline.")
                for m in await _team_members(db, team.id):
                    text, body = render(f"{when.capitalize()} left to submit", lines, ("Submit now", f"{base_url()}/participant?tab=build"))
                    if await queue(db, to_email=m.email, user_id=m.id, event_id=ev.id, kind="deadline_reminder",
                                   subject=f"Reminder: {rnd.name} closes in {when}", text=text, html_body=body,
                                   dedupe_key=f"remind:{rnd.id}:{team.id}:{m.id}:{int(deadline.timestamp())}:{window:g}"):
                        queued += 1
        await db.commit()
    return queued


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #

async def _attachment(db: AsyncSession, ref: Optional[str]) -> Optional[tuple[str, bytes]]:
    if not ref or not ref.startswith("certificate:"):
        return None
    from app.models.event import Event
    from app.models.platform_layer import Certificate
    from app.services.certificates import render_pdf

    cert = (await db.execute(select(Certificate).where(Certificate.id == ref.split(":", 1)[1]))).scalar_one_or_none()
    if cert is None or cert.revoked_at is not None:
        raise RuntimeError("certificate was revoked or deleted; not sending")
    ev = (await db.execute(select(Event).where(Event.id == cert.event_id))).scalar_one_or_none()
    pdf = await asyncio.to_thread(render_pdf, cert, ev.name if ev else "", f"{base_url()}/verify/{cert.code}")
    return f"certificate-{cert.code}.pdf", pdf


def _smtp_send(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        if settings.smtp_starttls:
            s.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            s.login(settings.smtp_username, settings.smtp_password)
        s.send_message(msg)


async def _send(row: EmailOutbox, attachment: Optional[tuple[str, bytes]]) -> None:
    reason = not_configured_reason()
    if reason:
        raise RuntimeError(reason)
    provider = settings.mail_provider.lower()
    name, addr = parseaddr(settings.mail_from)
    if provider == "sendgrid":
        import base64

        sender = {"email": addr or settings.mail_from}
        if name:
            sender["name"] = name
        payload: dict = {
            "personalizations": [{"to": [{"email": row.to_email}]}],
            "from": sender,
            "subject": row.subject,
            # text/plain must come before text/html (SendGrid requirement)
            "content": [{"type": "text/plain", "value": row.body_text}, {"type": "text/html", "value": row.body_html}],
            "categories": [row.kind],
        }
        if attachment:
            payload["attachments"] = [{"content": base64.b64encode(attachment[1]).decode(), "filename": attachment[0],
                                       "type": "application/pdf", "disposition": "attachment"}]
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post("https://api.sendgrid.com/v3/mail/send", json=payload,
                                  headers={"Authorization": f"Bearer {settings.sendgrid_api_key.strip()}"})
        if r.status_code >= 300:
            detail = r.text[:180]
            try:
                detail = "; ".join(e.get("message", "") for e in r.json().get("errors", [])) or detail
            except ValueError:
                pass
            raise RuntimeError(f"SendGrid answered HTTP {r.status_code}: {detail}")
        return
    msg = EmailMessage()
    msg["From"] = formataddr((name, addr)) if addr else settings.mail_from
    msg["To"] = row.to_email
    msg["Subject"] = row.subject
    msg["X-Launchpad-Kind"] = row.kind
    msg.set_content(row.body_text)
    msg.add_alternative(row.body_html, subtype="html")
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
    await asyncio.to_thread(_smtp_send, msg)


def _delays() -> list[float]:
    return [float(x) for x in settings.mail_retry_delays.split(",") if x.strip()]


async def _deliver(email_id: str) -> None:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(EmailOutbox).where(EmailOutbox.id == email_id))).scalar_one_or_none()
        if row is None or row.status != "pending":
            return
        now = datetime.now(timezone.utc)
        error = None
        try:
            attachment = await _attachment(db, row.attachment_ref)
            await _send(row, attachment)
        except Exception as exc:  # noqa: BLE001
            error = (str(exc) or exc.__class__.__name__)[:280]
        row.attempts += 1
        if error is None:
            row.status, row.error, row.sent_at = "sent", None, now
            log.info("email sent: %s -> %s (%s)", row.kind, row.to_email, settings.mail_provider)
        else:
            log.warning("email not sent (attempt %d): %s -> %s: %s", row.attempts, row.kind, row.to_email, error)
            row.error = error
            delays = _delays()
            if row.attempts > len(delays) or "revoked" in error:
                row.status = "failed"
            else:
                row.next_attempt_at = now + timedelta(seconds=delays[row.attempts - 1])
        await db.commit()


async def process_due(limit: int = 20) -> int:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        due = (await db.execute(
            select(EmailOutbox.id, EmailOutbox.next_attempt_at)
            .where(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= now)
            .order_by(EmailOutbox.next_attempt_at).limit(limit)
        )).all()
        claimed = []
        for eid, due_at in due:
            res = await db.execute(
                update(EmailOutbox).where(EmailOutbox.id == eid, EmailOutbox.next_attempt_at == due_at, EmailOutbox.status == "pending")
                .values(next_attempt_at=now + timedelta(seconds=90))
            )
            if res.rowcount == 1:
                claimed.append(eid)
        await db.commit()
    # Sequential on purpose: providers rate-limit bursts.
    for eid in claimed:
        await _deliver(eid)
    return len(claimed)


_last_sweep = 0.0


async def tick() -> None:
    """Called from the background dispatcher loop every couple of seconds."""
    global _last_sweep
    if time.monotonic() - _last_sweep > 60:
        _last_sweep = time.monotonic()
        try:
            await sweep_reminders()
        except Exception:  # noqa: BLE001
            log.exception("reminder sweep failed")
    await process_due()
