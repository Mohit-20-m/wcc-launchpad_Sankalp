"""Bulk CSV import. Everything is validated FIRST (a dry run reports every
row), and a real import is all-or-nothing unless the organizer chooses to
skip bad rows. Three kinds: teams, projects, judge assignments."""
import csv
import io
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.event import Event, Track
from app.models.judging import JudgeAssignment
from app.models.project import Project, SubmissionStatus
from app.models.round import Round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.services.audit import audit
from app.services.submissions import delete_project_files

MAX_ROWS = 5000
MAX_BYTES = 2 * 1024 * 1024
MAX_TEAM = 4

COLUMNS = {
    "teams": ["team_name", "member_email", "member_name"],
    "projects": ["team_name", "title", "summary", "tech_stack", "repo_url", "video_url", "track", "round"],
    "assignments": ["judge_email", "project_title", "team_name"],
}
REQUIRED = {"teams": ["team_name", "member_email"], "projects": ["team_name", "title"], "assignments": ["judge_email"]}
EXAMPLES = {
    "teams": ["Null Pointers,ada@example.org,Ada Lovelace", "Null Pointers,alan@example.org,Alan Turing"],
    "projects": ["Null Pointers,Quiet Hours,A calm inbox,Python;React,https://github.com/x/y,,AI,1"],
    "assignments": ["judge@example.org,Quiet Hours,Null Pointers"],
}


def template(kind: str) -> str:
    return ",".join(COLUMNS[kind]) + "\n" + "\n".join(EXAMPLES[kind]) + "\n"


def _clean(value: Optional[str]) -> str:
    v = (value or "").strip()
    # Undo the apostrophe our own exports add against spreadsheet formula injection.
    return v[1:] if len(v) > 1 and v[0] == "'" and v[1] in "=+-@" else v


def parse(raw: bytes, kind: str) -> tuple[list[tuple[int, dict[str, str]]], list[str]]:
    if len(raw) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "That file is over 2 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file isn't UTF-8 text. Save it as CSV (UTF-8).")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED[kind] if c not in header]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(COLUMNS[kind])}.")
    warnings = [f"Ignoring unknown column '{h}'." for h in header if h and h not in COLUMNS[kind]]
    rows = []
    for i, r in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Too many rows (limit {MAX_ROWS}).")
        clean = {(k or "").strip().lower(): _clean(v) for k, v in r.items() if k}
        if any(clean.values()):
            rows.append((i, clean))
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file has no data rows.")
    return rows, warnings


def _valid_email(e: str) -> Optional[str]:
    try:
        return validate_email(e, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def _valid_url(u: str) -> bool:
    return bool(re.match(r"^https?://[^\s/]+\.[^\s/]+\S*$|^https?://localhost\S*$", u)) and len(u) <= 500


class Plan:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.ops: list[dict[str, Any]] = []

    def add(self, line: int, st: str, msg: str = "") -> None:
        self.results.append({"row": line, "status": st, "message": msg})

    @property
    def errors(self) -> int:
        return sum(r["status"] == "error" for r in self.results)


async def _plan_teams(db: AsyncSession, event: Event, rows, create_accounts: bool) -> Plan:
    plan = Plan()
    emails = {e for _, r in rows if (e := _valid_email(r.get("member_email", "")))}
    users = {u.email.lower(): u for u in (await db.execute(select(User).where(User.email.in_(emails)))).scalars().all()} if emails else {}
    existing_names = {n.lower() for (n,) in (await db.execute(select(Team.name).where(Team.event_id == event.id))).all()}
    busy = {uid for (uid,) in (await db.execute(select(TeamMember.user_id).join(Team, Team.id == TeamMember.team_id).where(Team.event_id == event.id))).all()}
    seen_email: dict[str, str] = {}
    teams: dict[str, dict[str, Any]] = {}
    for line, r in rows:
        name, raw_email = r.get("team_name", ""), r.get("member_email", "")
        email = _valid_email(raw_email)
        if not name or len(name) > 255:
            plan.add(line, "error", "Team name is required (max 255 characters)."); continue
        if name.lower() in existing_names:
            plan.add(line, "error", f"A team called '{name}' already exists in this event."); continue
        if email is None:
            plan.add(line, "error", f"'{raw_email}' isn't a valid email address."); continue
        if email in seen_email and seen_email[email] != name.lower():
            plan.add(line, "error", f"{email} appears in two different teams in this file."); continue
        user = users.get(email)
        if user is not None and user.role != UserRole.PARTICIPANT:
            plan.add(line, "error", f"{email} is a {user.role.value} account, not a participant."); continue
        if user is not None and user.id in busy:
            plan.add(line, "error", f"{email} is already on a team in this event."); continue
        if user is None and not create_accounts:
            plan.add(line, "error", f"No account for {email}. Tick 'create accounts' to make one."); continue
        t = teams.setdefault(name.lower(), {"name": name, "members": []})
        if any(m["email"] == email for m in t["members"]):
            plan.add(line, "skip", "Duplicate row for this member."); continue
        if len(t["members"]) >= MAX_TEAM:
            plan.add(line, "error", f"Team '{name}' would have more than {MAX_TEAM} people."); continue
        seen_email[email] = name.lower()
        t["members"].append({"email": email, "name": r.get("member_name") or email.split("@")[0], "user": user, "line": line})
        plan.add(line, "ok", "Will create the account." if user is None else "")
    plan.ops = [{"team": t["name"], "members": t["members"]} for t in teams.values() if t["members"]]
    return plan


async def _plan_projects(db: AsyncSession, event: Event, rows) -> Plan:
    plan = Plan()
    teams = {t.name.lower(): t for t in (await db.execute(select(Team).where(Team.event_id == event.id))).scalars().all()}
    tracks = {t.name.lower(): t.id for t in (await db.execute(select(Track).where(Track.event_id == event.id))).scalars().all()}
    rounds = {r.number: r for r in (await db.execute(select(Round).where(Round.event_id == event.id))).scalars().all()}
    seen: set[tuple[str, int]] = set()
    for line, r in rows:
        team = teams.get(r.get("team_name", "").lower())
        title = r.get("title", "")
        if team is None:
            plan.add(line, "error", f"No team called '{r.get('team_name', '')}' in this event (import teams first)."); continue
        if not title or len(title) > 255:
            plan.add(line, "error", "Title is required (max 255 characters)."); continue
        try:
            number = int(r["round"]) if r.get("round") else 1
        except ValueError:
            plan.add(line, "error", f"Round '{r.get('round')}' isn't a number."); continue
        rnd = rounds.get(number)
        if rnd is None:
            plan.add(line, "error", f"This event has no round {number}."); continue
        bad = next((f for f in ("repo_url", "video_url") if r.get(f) and not _valid_url(r[f])), None)
        if bad:
            plan.add(line, "error", f"{bad} must be a full http(s) link."); continue
        track_id = None
        if r.get("track"):
            track_id = tracks.get(r["track"].lower())
            if track_id is None:
                plan.add(line, "error", f"Unknown track '{r['track']}'. Tracks: {', '.join(sorted(tracks)) or 'none'}."); continue
        if len(r.get("summary", "")) > 10000 or len(r.get("tech_stack", "")) > 500:
            plan.add(line, "error", "Summary is limited to 10,000 characters and tech stack to 500."); continue
        if (team.id, number) in seen:
            plan.add(line, "error", f"'{team.name}' already has a row for round {number} in this file."); continue
        seen.add((team.id, number))
        plan.ops.append({"team": team, "round": rnd, "track_id": track_id, "row": r, "line": line})
        plan.add(line, "ok")
    return plan


async def _plan_assignments(db: AsyncSession, event: Event, rows) -> Plan:
    plan = Plan()
    judges = {u.email.lower(): u for u in (await db.execute(select(User).where(User.role == UserRole.JUDGE))).scalars().all()}
    projects = (await db.execute(
        select(Project, Team).join(Team, Team.id == Project.team_id).where(Team.event_id == event.id, Project.status != SubmissionStatus.DRAFT)
    )).all()
    members = {}
    for uid, tid in (await db.execute(select(TeamMember.user_id, TeamMember.team_id).join(Team, Team.id == TeamMember.team_id).where(Team.event_id == event.id))).all():
        members.setdefault(uid, set()).add(tid)
    have = {(j, p) for j, p in (await db.execute(select(JudgeAssignment.judge_user_id, JudgeAssignment.project_id).where(JudgeAssignment.event_id == event.id))).all()}
    planned: set[tuple[str, str]] = set()
    for line, r in rows:
        judge = judges.get((r.get("judge_email") or "").lower())
        if judge is None:
            plan.add(line, "error", f"No judge account for '{r.get('judge_email', '')}'."); continue
        title, tname = (r.get("project_title") or "").lower(), (r.get("team_name") or "").lower()
        if not title and not tname:
            plan.add(line, "error", "Give a project_title or a team_name."); continue
        matches = [p for p, t in projects if (not title or p.title.lower() == title) and (not tname or t.name.lower() == tname)]
        if not matches:
            plan.add(line, "error", "No submitted project matches that title/team."); continue
        if len(matches) > 1:
            plan.add(line, "error", f"{len(matches)} projects match; add team_name (and use a unique title)."); continue
        p = matches[0]
        if p.team_id in members.get(judge.id, set()):
            plan.add(line, "error", f"{judge.email} is on that team (automatic conflict of interest)."); continue
        if (judge.id, p.id) in have or (judge.id, p.id) in planned:
            plan.add(line, "skip", "Already assigned."); continue
        planned.add((judge.id, p.id))
        plan.ops.append({"judge": judge, "project": p})
        plan.add(line, "ok")
    return plan


async def run_import(db: AsyncSession, event: Event, organizer: User, kind: str, raw: bytes, *, dry_run: bool, create_accounts: bool, skip_errors: bool) -> dict[str, Any]:
    rows, warnings = parse(raw, kind)
    if kind == "teams":
        plan = await _plan_teams(db, event, rows, create_accounts)
    elif kind == "projects":
        plan = await _plan_projects(db, event, rows)
    else:
        plan = await _plan_assignments(db, event, rows)

    out: dict[str, Any] = {
        "kind": kind, "dry_run": dry_run, "total": len(rows), "ok": sum(r["status"] == "ok" for r in plan.results),
        "skipped": sum(r["status"] == "skip" for r in plan.results), "errors": plan.errors, "committed": False,
        "rows": plan.results, "warnings": warnings, "created_accounts": [],
    }
    if dry_run:
        return out
    if plan.errors and not skip_errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{plan.errors} row(s) have problems, so nothing was imported. Fix them, or import only the valid rows.")
    if not plan.ops:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "There is nothing valid to import.")

    now = datetime.now(timezone.utc)
    created = 0
    if kind == "teams":
        for op in plan.ops:
            team = Team(event_id=event.id, name=op["team"], invite_code=secrets.token_urlsafe(6))
            db.add(team)
            await db.flush()
            for i, m in enumerate(op["members"]):
                user = m["user"]
                if user is None:
                    temp = secrets.token_urlsafe(9)
                    user = User(email=m["email"], name=m["name"][:255], password_hash=hash_password(temp), role=UserRole.PARTICIPANT)
                    db.add(user)
                    await db.flush()
                    out["created_accounts"].append({"email": m["email"], "name": user.name, "temp_password": temp})
                db.add(TeamMember(team_id=team.id, user_id=user.id, is_leader=(i == 0)))
            await audit(db, "team.create", event_id=event.id, actor=organizer, target_type="team", target_id=team.id, detail={"name": team.name, "imported": True, "members": len(op["members"])})
            created += 1
    elif kind == "projects":
        for op in plan.ops:
            r, team, rnd = op["row"], op["team"], op["round"]
            existing = (await db.execute(select(Project).where(Project.team_id == team.id, Project.round_id == rnd.id))).scalar_one_or_none()
            files = 0
            if existing is None:
                project, action = Project(team_id=team.id, round_id=rnd.id), "submission.create"
                db.add(project)
            else:
                project, action = existing, "submission.replace"
                files = await delete_project_files(db, project.id)
            project.title, project.summary = r["title"], r.get("summary") or None
            project.tech_stack, project.repo_url, project.video_url = r.get("tech_stack") or None, r.get("repo_url") or None, r.get("video_url") or None
            project.track_id, project.status, project.submitted_at, project.updated_at = op["track_id"], SubmissionStatus.SUBMITTED, now, now
            await db.flush()
            await audit(db, action, event_id=event.id, actor=organizer, target_type="project", target_id=project.id, detail={"team": team.name, "round": rnd.number, "imported": True, "files_deleted": files})
            created += 1
    else:
        for op in plan.ops:
            db.add(JudgeAssignment(event_id=event.id, judge_user_id=op["judge"].id, project_id=op["project"].id))
            await audit(db, "judge.assign", event_id=event.id, actor=organizer, target_type="project", target_id=op["project"].id, detail={"judge": op["judge"].email, "imported": True})
            created += 1
    await audit(db, "import.commit", event_id=event.id, actor=organizer, target_type="event", target_id=event.id,
                detail={"kind": kind, "created": created, "errors_skipped": plan.errors, "accounts_created": len(out["created_accounts"])})
    await db.commit()
    out["committed"], out["created"] = True, created
    return out
