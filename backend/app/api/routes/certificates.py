"""Certificates of participation, achievement and service, with public
verification and a downloadable PDF."""
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.net import request_ip_hash
from app.core.ownership import get_event_or_404, get_owned_event
from app.core.security import get_current_user, require_role
from app.models.event import Event, Prize
from app.models.judging import Score
from app.models.project import Project, SubmissionStatus
from app.models.platform_layer import Certificate
from app.models.team import Team, TeamMember
from app.models.user import User, UserRole
from app.models.voting import PrizeAward
from app.services.audit import audit
from app.services.certificates import normalize_code, new_code, render_pdf, signature_for, signature_ok
from app.services.ratelimit import limiter

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))
Kind = Literal["participation", "winner", "judge"]


class IssueRequest(BaseModel):
    kinds: list[Kind] = ["participation", "winner", "judge"]
    # Email each NEW certificate (PDF attached) to its recipient. Respects the
    # event's "certificate emails" switch; re-issuing never emails twice.
    send_email: bool = True


class CertOut(BaseModel):
    id: str
    code: str
    kind: str
    title: str
    recipient_name: str
    event_id: str
    event_name: str
    team_name: Optional[str]
    project_title: Optional[str]
    rank: Optional[int]
    issued_at: datetime
    revoked: bool


class VerifyOut(BaseModel):
    valid: bool
    revoked: bool
    genuine: bool  # the signature over the contents checks out
    code: str
    kind: str
    title: str
    recipient_name: str
    event_name: str
    team_name: Optional[str]
    project_title: Optional[str]
    rank: Optional[int]
    issued_at: datetime


def _out(c: Certificate, event_name: str) -> CertOut:
    return CertOut(id=c.id, code=c.code, kind=c.kind, title=c.title, recipient_name=c.recipient_name, event_id=c.event_id, event_name=event_name,
                   team_name=c.team_name, project_title=c.project_title, rank=c.rank, issued_at=c.issued_at, revoked=c.revoked_at is not None)


def _base_url(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{proto}://{request.headers.get('host') or request.url.netloc}"


@router.post("/events/{event_id}/certificates/issue")
async def issue(event_id: str, payload: IssueRequest, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    kinds = set(payload.kinds)
    if "winner" in kinds and event.results_published_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Publish the results before issuing winner certificates.")
    existing = {(u, k, t) for u, k, t in (await db.execute(select(Certificate.user_id, Certificate.kind, Certificate.title).where(Certificate.event_id == event_id))).all()}
    wanted: list[dict] = []

    teams = {t.id: t for t in (await db.execute(select(Team).where(Team.event_id == event_id))).scalars().all()}
    members: dict[str, list[User]] = {}
    for tid, user in (await db.execute(select(TeamMember.team_id, User).join(User, User.id == TeamMember.user_id).where(TeamMember.team_id.in_(list(teams) or [""])))).all():
        members.setdefault(tid, []).append(user)
    projects = (await db.execute(select(Project).where(Project.team_id.in_(list(teams) or [""]), Project.status != SubmissionStatus.DRAFT))).scalars().all()
    latest: dict[str, Project] = {}
    for p in projects:
        cur = latest.get(p.team_id)
        if cur is None or (p.submitted_at and (cur.submitted_at is None or p.submitted_at > cur.submitted_at)):
            latest[p.team_id] = p

    if "participation" in kinds:
        for tid, p in latest.items():
            for u in members.get(tid, []):
                wanted.append(dict(user=u, kind="participation", title=event.name, team=teams[tid].name, project=p.title, rank=None))
    if "winner" in kinds:
        prizes = {pz.id: pz for pz in (await db.execute(select(Prize).where(Prize.event_id == event_id))).scalars().all()}
        proj_by_id = {p.id: p for p in projects}
        for a in (await db.execute(select(PrizeAward).where(PrizeAward.event_id == event_id))).scalars().all():
            p = proj_by_id.get(a.project_id)
            if p is None or a.prize_id not in prizes:
                continue
            for u in members.get(p.team_id, []):
                wanted.append(dict(user=u, kind="winner", title=prizes[a.prize_id].name, team=teams[p.team_id].name, project=p.title, rank=a.rank))
    if "judge" in kinds:
        judge_ids = {j for (j,) in (await db.execute(select(Score.judge_user_id).join(Project, Project.id == Score.project_id).join(Team, Team.id == Project.team_id).where(Team.event_id == event_id))).all()}
        if judge_ids:
            for u in (await db.execute(select(User).where(User.id.in_(judge_ids)))).scalars().all():
                wanted.append(dict(user=u, kind="judge", title="Judge", team=None, project=None, rank=None))

    issued = {"participation": 0, "winner": 0, "judge": 0}
    skipped = 0
    fresh: list[tuple[Certificate, str]] = []
    now = datetime.now(timezone.utc)
    for w in wanted:
        if (w["user"].id, w["kind"], w["title"]) in existing:
            skipped += 1
            continue
        existing.add((w["user"].id, w["kind"], w["title"]))
        cid, code = str(uuid.uuid4()), new_code()
        cert = Certificate(id=cid, event_id=event_id, user_id=w["user"].id, recipient_name=w["user"].name, kind=w["kind"], title=w["title"], team_name=w["team"],
                           project_title=w["project"], rank=w["rank"], code=code, issued_at=now, issued_by=organizer.id,
                           signature=signature_for(cid, event_id, w["user"].id, w["user"].name, w["kind"], w["title"], w["rank"], now, code))
        db.add(cert)
        fresh.append((cert, w["user"].email))
        issued[w["kind"]] += 1
    await audit(db, "certificate.issue", event_id=event_id, actor=organizer, target_type="event", target_id=event_id, detail={"issued": issued, "already_had": skipped})
    emailed = 0
    if payload.send_email and fresh:
        from app.services import mailer

        if (await mailer.event_settings(db, event_id)).certificate_emails:
            await db.flush()
            for cert, email in fresh:
                emailed += int(await mailer.queue_certificate(db, cert, event.name, email))
    await db.commit()
    return {"issued": issued, "total_issued": sum(issued.values()), "already_had": skipped, "emailed": emailed}


@router.get("/events/{event_id}/certificates", response_model=list[CertOut])
async def list_event_certs(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    rows = (await db.execute(select(Certificate).where(Certificate.event_id == event_id).order_by(Certificate.kind, Certificate.recipient_name))).scalars().all()
    return [_out(c, event.name) for c in rows]


@router.post("/events/{event_id}/certificates/{cert_id}/revoke", response_model=CertOut)
async def revoke(event_id: str, cert_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    event = await get_owned_event(db, event_id, organizer)
    c = (await db.execute(select(Certificate).where(Certificate.id == cert_id, Certificate.event_id == event_id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found.")
    if c.revoked_at is None:
        c.revoked_at = datetime.now(timezone.utc)
        await audit(db, "certificate.revoke", event_id=event_id, actor=organizer, target_type="certificate", target_id=c.id, detail={"code": c.code, "kind": c.kind})
        await db.commit()
    return _out(c, event.name)


@router.get("/certificates/mine", response_model=list[CertOut])
async def mine(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(select(Certificate, Event.name).join(Event, Event.id == Certificate.event_id).where(Certificate.user_id == user.id).order_by(Certificate.issued_at.desc()))).all()
    return [_out(c, name) for c, name in rows if c.revoked_at is None]


async def _by_code(db: AsyncSession, request: Request, code: str) -> tuple[Certificate, str]:
    # Public and unauthenticated, so throttle guessing per address.
    if not await limiter.allow(f"cert:{request_ip_hash(request)}", 60, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many lookups. Try again in a minute.")
    row = (await db.execute(select(Certificate, Event.name).join(Event, Event.id == Certificate.event_id).where(Certificate.code == normalize_code(code)))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No certificate has that code.")
    return row[0], row[1]


@router.get("/certificates/verify/{code}", response_model=VerifyOut)
async def verify(code: str, request: Request, db: AsyncSession = Depends(get_db)):
    c, event_name = await _by_code(db, request, code)
    genuine = signature_ok(c)
    return VerifyOut(valid=genuine and c.revoked_at is None, revoked=c.revoked_at is not None, genuine=genuine, code=c.code, kind=c.kind, title=c.title,
                     recipient_name=c.recipient_name, event_name=event_name, team_name=c.team_name, project_title=c.project_title, rank=c.rank, issued_at=c.issued_at)


@router.get("/certificates/{code}/pdf")
async def pdf(code: str, request: Request, db: AsyncSession = Depends(get_db)):
    c, event_name = await _by_code(db, request, code)
    if c.revoked_at is not None or not signature_ok(c):
        raise HTTPException(status.HTTP_410_GONE, "This certificate is no longer valid.")
    data = render_pdf(c, event_name, f"{_base_url(request)}/verify/{c.code}")
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="certificate-{c.code}.pdf"', "Cache-Control": "no-store"})
