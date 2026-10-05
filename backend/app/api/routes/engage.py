"""Routes for the Launchpad add-ons: email notifications, auto-assignment,
judge anomaly detection and code-level duplicate detection.

Every organizer route resolves its event through get_owned_event, the same
single door the rest of the platform uses, so data isolation between
organizers (and API-key event scoping) applies here unchanged.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.ownership import get_owned_event
from app.core.security import get_current_user, require_role
from app.models.engage import EmailOutbox, JudgeExpertise, MailPreference, MailSettings, RepoScan
from app.models.event import Event, Track
from app.models.invite import RoleInvite
from app.models.judging import ConflictDeclaration, JudgeAssignment, JudgingCriterion, Score
from app.models.project import Project, SubmissionStatus
from app.models.round import Round, TeamExtension
from app.models.platform_layer import Certificate
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.services import mailer
from app.services.anomaly import analyse
from app.services.assignment import JudgeIn, ProjectIn, plan
from app.services.audit import audit
from app.services.codescan import ScanError, compare_all, fetch_repo, parse_github, timeline_flags
from app.services.live import hub
from app.services.results import resolve_round

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))
log = logging.getLogger("launchpad.engage")


# =========================================================================== #
# Email notifications
# =========================================================================== #

class MailSettingsIO(BaseModel):
    enabled: bool = True
    reminders_enabled: bool = True
    reminder_hours: str = Field(default="24,3", max_length=60)
    certificate_emails: bool = True


class PrefsIO(BaseModel):
    reminders: bool = True
    updates: bool = True


class EmailList(BaseModel):
    emails: list[EmailStr] = Field(min_length=1, max_length=20)
    note: Optional[str] = Field(default=None, max_length=300)


def _row(e: EmailOutbox, full: bool = False) -> dict:
    out = {"id": e.id, "to_email": e.to_email, "kind": e.kind, "subject": e.subject, "status": e.status,
           "attempts": e.attempts, "error": e.error, "created_at": e.created_at, "sent_at": e.sent_at,
           "has_attachment": bool(e.attachment_ref)}
    if full:
        out["body_text"] = e.body_text
        out["body_html"] = e.body_html
    return out


@router.get("/mail/status")
async def mail_status(_u: User = Organizer):
    provider = settings.mail_provider.lower()
    return {
        "provider": provider,
        "configured": mailer.not_configured_reason() is None,
        "problem": mailer.not_configured_reason(),
        "from": settings.mail_from,
        "smtp": f"{settings.smtp_host}:{settings.smtp_port}" if provider == "smtp" and settings.smtp_host else None,
        "skipped_domains": sorted(mailer.skip_domains()),
        "github_token": bool(settings.github_token),
        "links_point_to": mailer.base_url(),
    }


@router.get("/events/{event_id}/mail/settings", response_model=MailSettingsIO)
async def get_mail_settings(event_id: str, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    s = await mailer.event_settings(db, event_id)
    return MailSettingsIO(enabled=s.enabled, reminders_enabled=s.reminders_enabled, reminder_hours=s.reminder_hours, certificate_emails=s.certificate_emails)


@router.put("/events/{event_id}/mail/settings", response_model=MailSettingsIO)
async def put_mail_settings(event_id: str, payload: MailSettingsIO, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    hours = mailer._hours(payload.reminder_hours)
    if payload.reminders_enabled and not hours:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Reminder hours must be numbers like 24,3 (between 0 and 336).")
    row = (await db.execute(select(MailSettings).where(MailSettings.event_id == event_id))).scalar_one_or_none()
    if row is None:
        row = MailSettings(event_id=event_id)
        db.add(row)
    row.enabled, row.reminders_enabled, row.certificate_emails = payload.enabled, payload.reminders_enabled, payload.certificate_emails
    row.reminder_hours = ",".join(f"{h:g}" for h in hours) or "24,3"
    await audit(db, "mail.settings", event_id=event_id, actor=user, target_type="event", target_id=event_id, detail=payload.model_dump())
    await db.commit()
    return MailSettingsIO(enabled=row.enabled, reminders_enabled=row.reminders_enabled, reminder_hours=row.reminder_hours, certificate_emails=row.certificate_emails)


@router.get("/events/{event_id}/mail/outbox")
async def outbox(event_id: str, status_filter: Optional[str] = None, limit: int = 200, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    stmt = select(EmailOutbox).where(EmailOutbox.event_id == event_id)
    if status_filter:
        stmt = stmt.where(EmailOutbox.status == status_filter)
    rows = (await db.execute(stmt.order_by(EmailOutbox.created_at.desc()).limit(max(1, min(limit, 500))))).scalars().all()
    counts = dict((await db.execute(select(EmailOutbox.status, func.count()).where(EmailOutbox.event_id == event_id).group_by(EmailOutbox.status))).all())
    return {"counts": {k: counts.get(k, 0) for k in ("pending", "sent", "failed", "skipped")}, "emails": [_row(r) for r in rows]}


async def _email(db: AsyncSession, event_id: str, email_id: str) -> EmailOutbox:
    row = (await db.execute(select(EmailOutbox).where(EmailOutbox.id == email_id, EmailOutbox.event_id == event_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such email for this event.")
    return row


@router.get("/events/{event_id}/mail/outbox/{email_id}")
async def outbox_item(event_id: str, email_id: str, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    return _row(await _email(db, event_id, email_id), full=True)


@router.post("/events/{event_id}/mail/outbox/{email_id}/retry")
async def outbox_retry(event_id: str, email_id: str, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    row = await _email(db, event_id, email_id)
    if row.status == "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already sent.")
    row.status, row.error, row.next_attempt_at = "pending", None, datetime.now(timezone.utc)
    await db.commit()
    return _row(row)


class TestMailIn(BaseModel):
    to: Optional[EmailStr] = None


@router.post("/events/{event_id}/mail/test")
async def mail_test(event_id: str, payload: Optional[TestMailIn] = None, db: AsyncSession = Depends(get_db), user: User = Organizer):
    """Send a test email to any address (default: your own account's)."""
    ev = await get_owned_event(db, event_id, user)
    to = str(payload.to) if payload and payload.to else user.email
    if mailer.is_skipped_domain(to):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{to} is a demo/reserved address and is never emailed. Enter a real address to test with.")
    text, body = mailer.render("Email is working", [f"This is a test email from {settings.platform_name} for {ev.name}.",
                                                    f"Provider: {settings.mail_provider}. If you can read this, participants will receive their notifications."])
    await mailer.queue(db, to_email=to, user_id=user.id, event_id=event_id, kind="test",
                       subject=f"Test email — {ev.name}", text=text, html_body=body)
    await db.commit()
    return {"queued_to": to, "configured": mailer.not_configured_reason() is None}


@router.post("/events/{event_id}/mail/remind-now")
async def remind_now(event_id: str, db: AsyncSession = Depends(get_db), user: User = Organizer):
    """Run the deadline-reminder sweep immediately (it also runs every
    minute). Idempotent: nobody gets the same reminder twice."""
    await get_owned_event(db, event_id, user)
    n = await mailer.sweep_reminders()
    return {"queued": n}


@router.get("/me/mail-preferences", response_model=PrefsIO)
async def get_prefs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    p = await mailer.user_prefs(db, user.id)
    return PrefsIO(reminders=p.reminders, updates=p.updates)


@router.put("/me/mail-preferences", response_model=PrefsIO)
async def put_prefs(payload: PrefsIO, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = (await db.execute(select(MailPreference).where(MailPreference.user_id == user.id))).scalar_one_or_none()
    if row is None:
        row = MailPreference(user_id=user.id)
        db.add(row)
    row.reminders, row.updates = payload.reminders, payload.updates
    await db.commit()
    return payload


@router.post("/teams/{team_id}/invite-email")
async def team_invite_email(team_id: str, payload: EmailList, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    member = (await db.execute(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user.id))).scalar_one_or_none()
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only team members can invite people to this team.")
    count = (await db.execute(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team_id))).scalar_one()
    if count >= 4:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your team already has 4 members.")
    ev = (await db.execute(select(Event).where(Event.id == team.event_id))).scalar_one()
    sent = await mailer.queue_team_invites(db, team, ev, user, [str(e) for e in payload.emails], payload.note)
    await audit(db, "team.invite_email", event_id=ev.id, actor=user, target_type="team", target_id=team.id, detail={"invited": sent})
    await db.commit()
    return {"queued": sent}


@router.post("/invites/{invite_id}/email")
async def judge_invite_email(invite_id: str, payload: EmailList, db: AsyncSession = Depends(get_db), user: User = Organizer):
    invite = (await db.execute(select(RoleInvite).where(RoleInvite.id == invite_id))).scalar_one_or_none()
    if invite is None or (user.role != UserRole.ADMIN and invite.created_by != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found.")
    if invite.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That invite was revoked.")
    event_name = "the event"
    if invite.event_id:
        ev = await get_owned_event(db, invite.event_id, user)
        event_name = ev.name
    sent = await mailer.queue_judge_invites(db, invite, event_name, user, [str(e) for e in payload.emails])
    await audit(db, "invite.email", event_id=invite.event_id, actor=user, target_type="invite", target_id=invite.id, detail={"emailed": sent})
    await db.commit()
    return {"queued": sent}


@router.post("/events/{event_id}/certificates/{cert_id}/email")
async def certificate_email(event_id: str, cert_id: str, db: AsyncSession = Depends(get_db), user: User = Organizer):
    ev = await get_owned_event(db, event_id, user)
    cert = (await db.execute(select(Certificate).where(Certificate.id == cert_id, Certificate.event_id == event_id))).scalar_one_or_none()
    if cert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found.")
    if cert.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Revoked certificates aren't emailed.")
    recipient = (await db.execute(select(User).where(User.id == cert.user_id))).scalar_one()
    await mailer.queue_certificate(db, cert, ev.name, recipient.email, force=True)
    await db.commit()
    return {"queued_to": recipient.email}


# =========================================================================== #
# Auto-balancing judge assignment
# =========================================================================== #

class ExpertiseIn(BaseModel):
    track_ids: list[str] = Field(default_factory=list, max_length=50)


class AutoAssignIn(BaseModel):
    round_id: Optional[str] = None
    judge_ids: Optional[list[str]] = None
    reviews_per_project: int = Field(default=3, ge=1, le=10)
    max_per_judge: Optional[int] = Field(default=None, ge=1, le=500)
    track_mode: Literal["prefer", "strict", "ignore"] = "prefer"
    dry_run: bool = True
    notify: bool = True


async def _judge_pool(db: AsyncSession, event_id: str) -> list[dict]:
    judges = (await db.execute(select(User).where(User.role == UserRole.JUDGE).order_by(User.name))).scalars().all()
    exp: dict[str, list[str]] = {}
    for e in (await db.execute(select(JudgeExpertise).where(JudgeExpertise.event_id == event_id))).scalars().all():
        exp.setdefault(e.judge_user_id, []).append(e.track_id)
    load = dict((await db.execute(select(JudgeAssignment.judge_user_id, func.count()).where(JudgeAssignment.event_id == event_id)
                                  .group_by(JudgeAssignment.judge_user_id))).all())
    return [{"id": j.id, "name": j.name, "email": j.email, "track_ids": sorted(exp.get(j.id, [])), "load": int(load.get(j.id, 0)),
             "in_event": j.id in exp or j.id in load} for j in judges]


@router.get("/events/{event_id}/expertise")
async def get_expertise(event_id: str, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    tracks = (await db.execute(select(Track).where(Track.event_id == event_id).order_by(Track.name))).scalars().all()
    return {"tracks": [{"id": t.id, "name": t.name} for t in tracks], "judges": await _judge_pool(db, event_id)}


@router.put("/events/{event_id}/expertise/{judge_user_id}")
async def put_expertise(event_id: str, judge_user_id: str, payload: ExpertiseIn, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    judge = (await db.execute(select(User).where(User.id == judge_user_id, User.role == UserRole.JUDGE))).scalar_one_or_none()
    if judge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such judge.")
    valid = {t for (t,) in (await db.execute(select(Track.id).where(Track.event_id == event_id))).all()}
    wanted = set(payload.track_ids)
    if wanted - valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Some tracks don't belong to this event.")
    for e in (await db.execute(select(JudgeExpertise).where(JudgeExpertise.event_id == event_id, JudgeExpertise.judge_user_id == judge_user_id))).scalars().all():
        if e.track_id not in wanted:
            await db.delete(e)
        else:
            wanted.discard(e.track_id)
    for t in wanted:
        db.add(JudgeExpertise(event_id=event_id, judge_user_id=judge_user_id, track_id=t))
    await db.commit()
    return {"judge_user_id": judge_user_id, "track_ids": sorted(set(payload.track_ids))}


@router.post("/events/{event_id}/auto-assign")
async def auto_assign(event_id: str, payload: AutoAssignIn, db: AsyncSession = Depends(get_db), user: User = Organizer):
    ev = await get_owned_event(db, event_id, user)
    rnd = await resolve_round(db, event_id, payload.round_id) if payload.round_id else None
    if rnd is None:
        # Default: the latest round that has any submissions.
        rnds = (await db.execute(select(Round).where(Round.event_id == event_id).order_by(Round.number))).scalars().all()
        with_subs = {r for (r,) in (await db.execute(select(Project.round_id).join(Team, Team.id == Project.team_id)
                                                     .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT))).all()}
        rnd = next((r for r in reversed(rnds) if r.id in with_subs), rnds[-1] if rnds else None)

    pstmt = (select(Project, Track.name).join(Team, Team.id == Project.team_id).outerjoin(Track, Track.id == Project.track_id)
             .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT))
    if rnd is not None:
        pstmt = pstmt.where(Project.round_id == rnd.id)
    prows = (await db.execute(pstmt)).all()
    if not prows:
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no submitted projects to assign in this round.")
    pids = [p.id for p, _ in prows]
    existing: dict[str, set[str]] = {}
    for j, p in (await db.execute(select(JudgeAssignment.judge_user_id, JudgeAssignment.project_id).where(JudgeAssignment.project_id.in_(pids)))).all():
        existing.setdefault(p, set()).add(j)

    pool = await _judge_pool(db, event_id)
    if payload.judge_ids is not None:
        chosen = set(payload.judge_ids)
        pool = [j for j in pool if j["id"] in chosen]
    else:
        in_event = [j for j in pool if j["in_event"]]
        pool = in_event or pool
    if not pool:
        raise HTTPException(status.HTTP_409_CONFLICT, "No judges to assign. Invite judges first.")

    # Conflicts: judges on a project's team, and declared conflicts.
    blocked: set[tuple[str, str]] = set()
    team_of = {p.id: p.team_id for p, _ in prows}
    members: dict[str, set[str]] = {}
    for tid, uid in (await db.execute(select(TeamMember.team_id, TeamMember.user_id).where(TeamMember.team_id.in_(set(team_of.values()))))).all():
        members.setdefault(tid, set()).add(uid)
    pool_ids = {j["id"] for j in pool}
    for pid, tid in team_of.items():
        for uid in members.get(tid, set()) & pool_ids:
            blocked.add((uid, pid))
    for j, p in (await db.execute(select(ConflictDeclaration.judge_user_id, ConflictDeclaration.project_id).where(ConflictDeclaration.project_id.in_(pids)))).all():
        blocked.add((j, p))

    result = plan(
        [JudgeIn(j["id"], j["name"], j["email"], set(j["track_ids"]), j["load"]) for j in pool],
        [ProjectIn(p.id, p.title, p.team_id, p.track_id, tn, existing.get(p.id, set())) for p, tn in prows],
        blocked, payload.reviews_per_project, payload.max_per_judge, payload.track_mode,
    )
    result["round"] = {"id": rnd.id, "name": rnd.name} if rnd else None
    result["dry_run"] = payload.dry_run
    if payload.dry_run or not result["assignments"]:
        return result

    per_judge: dict[str, tuple] = {}
    judge_rows = {u.id: u for u in (await db.execute(select(User).where(User.id.in_({a["judge_user_id"] for a in result["assignments"]})))).scalars().all()}
    for a in result["assignments"]:
        db.add(JudgeAssignment(event_id=event_id, judge_user_id=a["judge_user_id"], project_id=a["project_id"]))
        u = judge_rows[a["judge_user_id"]]
        per_judge.setdefault(u.id, (u, []))[1].append(a["project_title"])
    await audit(db, "judge.auto_assign", event_id=event_id, actor=user, target_type="round", target_id=rnd.id if rnd else None,
                detail={"assignments": len(result["assignments"]), "judges": len(per_judge), "reviews_per_project": payload.reviews_per_project,
                        "track_mode": payload.track_mode, "short": result["summary"]["projects_short"]})
    if payload.notify:
        result["emails_queued"] = await mailer.queue_assignment_batch(db, ev, per_judge)
    await db.commit()
    await hub.publish(event_id, "progress", "stats", "submissions")
    return result


# =========================================================================== #
# Judge score anomalies
# =========================================================================== #

@router.get("/events/{event_id}/anomalies")
async def anomalies(event_id: str, round_id: Optional[str] = None, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    rnd = await resolve_round(db, event_id, round_id)
    weights = {c.name: float(c.weight) for c in (await db.execute(select(JudgingCriterion).where(JudgingCriterion.event_id == event_id))).scalars().all()}
    stmt = select(Score).join(Project, Project.id == Score.project_id).join(Team, Team.id == Project.team_id).where(Team.event_id == event_id)
    if rnd is not None:
        stmt = stmt.where(Project.round_id == rnd.id)
    scores = (await db.execute(stmt)).scalars().all()
    jids = {s.judge_user_id for s in scores}
    pids = {s.project_id for s in scores}
    info = {u.id: (u.name, u.email) for u in (await db.execute(select(User).where(User.id.in_(jids or {""})))).scalars().all()}
    titles = {p.id: p.title for p in (await db.execute(select(Project).where(Project.id.in_(pids or {""})))).scalars().all()}
    out = analyse(scores, weights, info, titles)
    out["round"] = {"id": rnd.id, "name": rnd.name} if rnd else None
    return out


# =========================================================================== #
# Code-level duplicate detection + repository timeline
# =========================================================================== #

_running: dict[str, asyncio.Task] = {}


class ScanIn(BaseModel):
    round_id: Optional[str] = None
    force: bool = False


async def _scan_event(event_id: str, project_ids: list[str], force: bool) -> None:
    for pid in project_ids:
        async with AsyncSessionLocal() as db:
            p = (await db.execute(select(Project).where(Project.id == pid))).scalar_one_or_none()
            if p is None:
                continue
            row = (await db.execute(select(RepoScan).where(RepoScan.project_id == pid))).scalar_one_or_none()
            if row is None:
                row = RepoScan(project_id=pid, event_id=event_id)
                db.add(row)
            gh = parse_github(p.repo_url)
            if row.status == "done" and not force and gh and row.repo and row.repo.lower() == f"{gh[0]}/{gh[1]}".lower():
                continue
            if gh is None:
                row.status, row.error, row.repo = "skipped", ("No repository link." if not p.repo_url else "Not a GitHub repository link."), None
                row.fingerprints = None
                await db.commit()
                continue
            row.status, row.error, row.repo = "pending", None, f"{gh[0]}/{gh[1]}"
            await db.commit()
            try:
                info = await fetch_repo(*gh)
                row.repo, row.commit_sha, row.is_fork, row.fork_parent = info["repo"], info["commit_sha"], info["is_fork"], info["fork_parent"]
                row.commit_count, row.first_commit_at, row.last_commit_at = info["commit_count"], info["first_commit_at"], info["last_commit_at"]
                row.fingerprints, row.file_count, row.status, row.error = info["fingerprints"], info["file_count"], "done", None
            except ScanError as exc:
                row.status, row.error = "error", str(exc)[:290]
                if "rate limit" in str(exc):
                    await db.commit()
                    # Mark the rest so the organizer sees why, then stop.
                    for rest in project_ids[project_ids.index(pid) + 1:]:
                        r2 = (await db.execute(select(RepoScan).where(RepoScan.project_id == rest))).scalar_one_or_none()
                        if r2 is not None and r2.status == "pending":
                            r2.status, r2.error = "error", "Not scanned: GitHub rate limit reached."
                    await db.commit()
                    break
            except Exception as exc:  # noqa: BLE001 -- offline, DNS, timeouts
                row.status, row.error = "error", f"Couldn't reach GitHub ({exc.__class__.__name__})."
            row.scanned_at = datetime.now(timezone.utc)
            await db.commit()
    async with AsyncSessionLocal() as db:
        await audit(db, "integrity.code_scan", event_id=event_id, actor_label="system", target_type="event", target_id=event_id,
                    detail={"projects": len(project_ids)})
        await db.commit()
    await hub.publish(event_id, "similarity")


async def _scan_projects(db: AsyncSession, event_id: str, round_id: Optional[str]):
    stmt = (select(Project, Team.name, Round.number).join(Team, Team.id == Project.team_id).outerjoin(Round, Round.id == Project.round_id)
            .where(Team.event_id == event_id, Project.status != SubmissionStatus.DRAFT))
    if round_id:
        stmt = stmt.where(Project.round_id == round_id)
    return (await db.execute(stmt.order_by(Project.title))).all()


@router.post("/events/{event_id}/code-scan")
async def start_scan(event_id: str, payload: ScanIn, db: AsyncSession = Depends(get_db), user: User = Organizer):
    await get_owned_event(db, event_id, user)
    task = _running.get(event_id)
    if task and not task.done():
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already running for this event.")
    rows = await _scan_projects(db, event_id, payload.round_id)
    ids = [p.id for p, _, _ in rows]
    for pid in ids:
        row = (await db.execute(select(RepoScan).where(RepoScan.project_id == pid))).scalar_one_or_none()
        if row is None:
            db.add(RepoScan(project_id=pid, event_id=event_id, status="pending"))
        elif payload.force or row.status != "done":
            row.status, row.error = "pending", None
    await audit(db, "integrity.code_scan_start", event_id=event_id, actor=user, target_type="event", target_id=event_id, detail={"projects": len(ids)})
    await db.commit()
    _running[event_id] = asyncio.create_task(_scan_event(event_id, ids, payload.force))
    return {"started": True, "projects": len(ids)}


@router.get("/events/{event_id}/code-scan")
async def scan_report(event_id: str, round_id: Optional[str] = None, db: AsyncSession = Depends(get_db), user: User = Organizer):
    ev = await get_owned_event(db, event_id, user)
    rows = await _scan_projects(db, event_id, round_id)
    scans = {s.project_id: s for s in (await db.execute(select(RepoScan).where(RepoScan.event_id == event_id))).scalars().all()}
    rounds = {r.id: r for r in (await db.execute(select(Round).where(Round.event_id == event_id))).scalars().all()}
    exts = {(e.round_id, e.team_id): e.closes_at for e in (await db.execute(select(TeamExtension).join(Round, Round.id == TeamExtension.round_id)
                                                                           .where(Round.event_id == event_id))).scalars().all()}
    first_open = min((r.opens_at for r in rounds.values() if r.opens_at), default=None)
    event_start = ev.starts_at or first_open
    forks_of = {}
    for p, tn, _ in rows:
        s = scans.get(p.id)
        if s and s.repo:
            forks_of[s.repo.lower()] = f"{tn} / {p.title}"

    projects, repos = [], []
    for p, team_name, rnum in rows:
        s = scans.get(p.id)
        flags = []
        if s and s.status == "done":
            rnd = rounds.get(p.round_id)
            deadline = exts.get((p.round_id, p.team_id)) or (rnd.closed_early_at or rnd.closes_at if rnd else ev.submissions_close)
            flags = timeline_flags(s, event_start, deadline, {k: v for k, v in forks_of.items() if k != (s.repo or "").lower()})
            repos.append({"project_id": p.id, "title": p.title, "team_id": p.team_id, "team_name": team_name, "round": rnum,
                          "repo": s.repo, "fingerprints": s.fingerprints or {}})
        projects.append({
            "project_id": p.id, "title": p.title, "team_name": team_name, "repo_url": p.repo_url,
            "status": s.status if s else "not_scanned", "error": s.error if s else None,
            "repo": s.repo if s else None, "files": s.file_count if s else 0, "commits": s.commit_count if s else None,
            "first_commit_at": s.first_commit_at if s else None, "last_commit_at": s.last_commit_at if s else None,
            "scanned_at": s.scanned_at if s else None, "flags": flags,
        })
    task = _running.get(event_id)
    pairs = await asyncio.to_thread(compare_all, repos)
    return {
        "running": bool(task and not task.done()),
        "event_start": event_start,
        "counts": {k: sum(1 for x in projects if x["status"] == k) for k in ("done", "pending", "error", "skipped", "not_scanned")},
        "flagged_projects": sum(1 for x in projects if x["flags"]),
        "pairs": pairs,
        "projects": projects,
        "github_token": bool(settings.github_token),
    }
