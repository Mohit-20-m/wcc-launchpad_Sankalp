"""Bulk CSV import (teams, projects, judge assignments) and per-event export."""
import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.event import Track
from app.models.judging import JudgingCriterion
from app.models.project import Project, ProjectFile
from app.models.round import Round
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.models.voting import PrizeAward
from app.services import importer
from app.services.csvsafe import safe_cell
from app.services.live import hub

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))


@router.get("/events/{event_id}/import/template")
async def import_template(event_id: str, kind: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    if kind not in importer.COLUMNS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kind must be teams, projects or assignments.")
    return Response(importer.template(kind), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="import-{kind}-template.csv"'})


@router.post("/events/{event_id}/import")
async def import_csv(
    event_id: str,
    kind: str = Form(...),
    dry_run: bool = Form(True),
    create_accounts: bool = Form(False),
    skip_errors: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    organizer: User = Organizer,
):
    event = await get_owned_event(db, event_id, organizer)
    if kind not in importer.COLUMNS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "kind must be teams, projects or assignments.")
    raw = await file.read(importer.MAX_BYTES + 1)
    result = await importer.run_import(db, event, organizer, kind, raw, dry_run=dry_run, create_accounts=create_accounts, skip_errors=skip_errors)
    if result["committed"]:
        await hub.publish(event_id, "stats", "teams", "submissions", "progress", "audit")
    return result


def _csv(rows: list[list], header: list[str], event_id: str, name: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([safe_cell(c) for c in r])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Export-Event": event_id})


@router.get("/events/{event_id}/export/projects.csv")
async def export_projects(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    tracks = {t.id: t.name for t in (await db.execute(select(Track).where(Track.event_id == event_id))).scalars().all()}
    rows = (await db.execute(
        select(Project, Team.name, Round.number).join(Team, Team.id == Project.team_id).outerjoin(Round, Round.id == Project.round_id)
        .where(Team.event_id == event_id).order_by(Round.number, Team.name)
    )).all()
    return _csv([[t, p.title, p.summary, p.tech_stack, p.repo_url, p.video_url, tracks.get(p.track_id or "", ""), n] for p, t, n in rows],
                importer.COLUMNS["projects"], event_id, "projects.csv")


@router.get("/events/{event_id}/export/teams.csv")
async def export_teams(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    rows = (await db.execute(
        select(Team.name, User.email, User.name).join(TeamMember, TeamMember.team_id == Team.id).join(User, User.id == TeamMember.user_id)
        .where(Team.event_id == event_id).order_by(Team.name, TeamMember.is_leader.desc(), User.email)
    )).all()
    return _csv([list(r) for r in rows], importer.COLUMNS["teams"], event_id, "teams.csv")


@router.get("/events/{event_id}/export/bundle.json")
async def export_bundle(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer, with_children=True)
    teams = (await db.execute(select(Team).where(Team.event_id == event_id).order_by(Team.name))).scalars().all()
    members: dict[str, list] = {}
    for tid, u, lead in (await db.execute(select(TeamMember.team_id, User, TeamMember.is_leader).join(User, User.id == TeamMember.user_id).where(TeamMember.team_id.in_([t.id for t in teams] or [""])))).all():
        members.setdefault(tid, []).append({"name": u.name, "email": u.email, "is_leader": lead})
    projects = (await db.execute(select(Project, Round.number).outerjoin(Round, Round.id == Project.round_id).where(Project.team_id.in_([t.id for t in teams] or [""])))).all()
    files: dict[str, list[str]] = {}
    for pid, fn in (await db.execute(select(ProjectFile.project_id, ProjectFile.filename).where(ProjectFile.project_id.in_([p.id for p, _ in projects] or [""])))).all():
        files.setdefault(pid, []).append(fn)
    criteria = (await db.execute(select(JudgingCriterion).where(JudgingCriterion.event_id == event_id))).scalars().all()
    awards = (await db.execute(select(PrizeAward).where(PrizeAward.event_id == event_id))).scalars().all()
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    bundle = {
        "format": "launchpad-event-bundle/1", "exported_at": datetime.now(timezone.utc).isoformat(),
        "event": {"id": event.id, "name": event.name, "description": event.description, "starts_at": iso(event.starts_at), "ends_at": iso(event.ends_at),
                  "submissions_close": iso(event.submissions_close), "results_published_at": iso(event.results_published_at),
                  "audit_anchor": {"seq": event.results_anchor_seq, "hash": event.results_anchor_hash} if event.results_anchor_hash else None},
        "rounds": [{"number": r.number, "name": r.name, "instructions": r.instructions, "opens_at": iso(r.opens_at), "closes_at": iso(r.closes_at), "closed_early_at": iso(r.closed_early_at),
                    "allow_idea": r.allow_idea, "allow_repo": r.allow_repo, "allow_video": r.allow_video, "allow_files": r.allow_files, "open_to_all": r.open_to_all} for r in event.rounds],
        "tracks": [t.name for t in event.tracks],
        "prizes": [{"name": p.name, "amount": float(p.amount) if p.amount is not None else None} for p in event.prizes],
        "criteria": [{"name": c.name, "weight": float(c.weight), "description": c.description} for c in criteria],
        "teams": [{"id": t.id, "name": t.name, "members": members.get(t.id, [])} for t in teams],
        "projects": [{"id": p.id, "team_id": p.team_id, "round": n, "title": p.title, "summary": p.summary, "tech_stack": p.tech_stack, "repo_url": p.repo_url,
                      "video_url": p.video_url, "status": p.status.value, "submitted_at": iso(p.submitted_at), "files": files.get(p.id, [])} for p, n in projects],
        "prize_awards": [{"prize_id": a.prize_id, "project_id": a.project_id, "rank": a.rank} for a in awards],
    }
    return Response(json.dumps(bundle, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="event-bundle.json"', "X-Export-Event": event_id})
