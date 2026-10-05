"""Webhook endpoints (per event) and their delivery log."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import require_role
from app.models.platform_layer import Webhook, WebhookDelivery
from app.models.user import User, UserRole
from app.services.audit import audit
from app.services.webhooks import EVENT_TYPES, check_url, new_secret

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))
MAX_HOOKS = 10


class HookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(default_factory=lambda: ["*"])


class HookPatch(BaseModel):
    url: Optional[str] = Field(default=None, max_length=500)
    events: Optional[list[str]] = None
    active: Optional[bool] = None


class HookOut(BaseModel):
    id: str
    url: str
    events: list[str]
    active: bool
    secret_hint: str
    consecutive_failures: int
    disabled_reason: Optional[str]
    created_at: datetime
    secret: Optional[str] = None  # only when created / rotated


class DeliveryOut(BaseModel):
    id: str
    event_type: str
    status: str
    attempts: int
    response_code: Optional[int]
    error: Optional[str]
    duration_ms: Optional[int]
    created_at: datetime
    delivered_at: Optional[datetime]
    next_attempt_at: Optional[datetime]
    payload: str


def _out(h: Webhook, secret: bool = False) -> HookOut:
    return HookOut(id=h.id, url=h.url, events=h.events.split(","), active=h.active, secret_hint="…" + h.secret[-4:], consecutive_failures=h.consecutive_failures,
                   disabled_reason=h.disabled_reason, created_at=h.created_at, secret=h.secret if secret else None)


def _events(values: list[str]) -> str:
    vals = sorted(set(v.strip() for v in values if v.strip()))
    if not vals or "*" in vals:
        return "*"
    bad = [v for v in vals if v not in EVENT_TYPES]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown event type(s): {', '.join(bad)}.")
    return ",".join(vals)


async def _hook(db: AsyncSession, event_id: str, hook_id: str) -> Webhook:
    h = (await db.execute(select(Webhook).where(Webhook.id == hook_id, Webhook.event_id == event_id))).scalar_one_or_none()
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found.")
    return h


@router.get("/webhook-event-types", response_model=list[str])
async def event_types():
    return EVENT_TYPES


@router.post("/events/{event_id}/webhooks", response_model=HookOut, status_code=status.HTTP_201_CREATED)
async def create_hook(event_id: str, payload: HookCreate, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    count = (await db.execute(select(func.count()).select_from(Webhook).where(Webhook.event_id == event_id))).scalar_one()
    if count >= MAX_HOOKS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"An event can have at most {MAX_HOOKS} webhooks.")
    problem = await check_url(payload.url.strip())
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    hook = Webhook(event_id=event_id, url=payload.url.strip(), secret=new_secret(), events=_events(payload.events), created_by=organizer.id)
    db.add(hook)
    await db.flush()
    await audit(db, "webhook.create", event_id=event_id, actor=organizer, target_type="webhook", target_id=hook.id, detail={"url": hook.url, "events": hook.events})
    await db.commit()
    return _out(hook, secret=True)


@router.get("/events/{event_id}/webhooks", response_model=list[HookOut])
async def list_hooks(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    return [_out(h) for h in (await db.execute(select(Webhook).where(Webhook.event_id == event_id).order_by(Webhook.created_at))).scalars().all()]


@router.patch("/events/{event_id}/webhooks/{hook_id}", response_model=HookOut)
async def patch_hook(event_id: str, hook_id: str, payload: HookPatch, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    hook = await _hook(db, event_id, hook_id)
    if payload.url is not None:
        problem = await check_url(payload.url.strip())
        if problem:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
        hook.url = payload.url.strip()
    if payload.events is not None:
        hook.events = _events(payload.events)
    if payload.active is not None:
        hook.active = payload.active
        if payload.active:
            hook.consecutive_failures, hook.disabled_reason = 0, None
    await audit(db, "webhook.update", event_id=event_id, actor=organizer, target_type="webhook", target_id=hook.id, detail={"active": hook.active, "events": hook.events})
    await db.commit()
    return _out(hook)


@router.delete("/events/{event_id}/webhooks/{hook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hook(event_id: str, hook_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    hook = await _hook(db, event_id, hook_id)
    hook.active = False
    pending = (await db.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id, WebhookDelivery.status == "pending"))).scalars().all()
    for d in pending:
        d.status, d.error = "failed", "endpoint deleted"
    hook.url, hook.disabled_reason = "https://deleted.invalid/", "deleted"
    hook.events = "-"
    await audit(db, "webhook.delete", event_id=event_id, actor=organizer, target_type="webhook", target_id=hook.id)
    await db.commit()


@router.post("/events/{event_id}/webhooks/{hook_id}/rotate-secret", response_model=HookOut)
async def rotate(event_id: str, hook_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    hook = await _hook(db, event_id, hook_id)
    hook.secret = new_secret()
    await audit(db, "webhook.rotate_secret", event_id=event_id, actor=organizer, target_type="webhook", target_id=hook.id)
    await db.commit()
    return _out(hook, secret=True)


@router.post("/events/{event_id}/webhooks/{hook_id}/test", response_model=DeliveryOut)
async def test_hook(event_id: str, hook_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    hook = await _hook(db, event_id, hook_id)
    if not hook.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This webhook is disabled. Re-enable it first.")
    now = datetime.now(timezone.utc)
    payload = {"id": str(uuid.uuid4()), "type": "webhook.test", "created_at": now.isoformat(), "event_id": event_id, "data": {"message": "This is a test delivery."}}
    d = WebhookDelivery(webhook_id=hook.id, event_id=event_id, event_type="webhook.test", payload=json.dumps(payload), next_attempt_at=now)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return _delivery(d)


def _delivery(d: WebhookDelivery) -> DeliveryOut:
    return DeliveryOut(id=d.id, event_type=d.event_type, status=d.status, attempts=d.attempts, response_code=d.response_code, error=d.error, duration_ms=d.duration_ms,
                       created_at=d.created_at, delivered_at=d.delivered_at, next_attempt_at=d.next_attempt_at if d.status == "pending" else None, payload=d.payload[:4000])


@router.get("/events/{event_id}/webhooks/{hook_id}/deliveries", response_model=list[DeliveryOut])
async def deliveries(event_id: str, hook_id: str, limit: int = 50, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    hook = await _hook(db, event_id, hook_id)
    rows = (await db.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id).order_by(WebhookDelivery.created_at.desc()).limit(min(max(limit, 1), 200)))).scalars().all()
    return [_delivery(d) for d in rows]


@router.post("/events/{event_id}/webhooks/{hook_id}/deliveries/{delivery_id}/retry", response_model=DeliveryOut)
async def retry(event_id: str, hook_id: str, delivery_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    await get_owned_event(db, event_id, organizer)
    hook = await _hook(db, event_id, hook_id)
    d = (await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id, WebhookDelivery.webhook_id == hook.id))).scalar_one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found.")
    if d.status == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "That delivery is still being attempted.")
    d.status, d.attempts, d.error, d.next_attempt_at = "pending", 0, None, datetime.now(timezone.utc)
    await db.commit()
    return _delivery(d)
