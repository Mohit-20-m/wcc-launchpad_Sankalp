"""Outbound webhooks.

* Events come from the audit trail (`services/audit.py` calls
  `enqueue_for_action`), so anything the audit log records can be announced,
  and an event is queued in the SAME transaction as the action (an outbox):
  never lost, never sent for something that rolled back.
* Bodies are signed: `X-Launchpad-Signature: t=<unix>,v1=<hex>` where
  v1 = HMAC-SHA256(secret, f"{t}.{raw_body}"). Receivers should also reject a
  stale `t` to stop replays.
* Delivery retries with backoff; an endpoint that keeps failing is disabled.
* URLs are validated to stop the platform being aimed at internal services
  (SSRF), both when saved and again right before every send (DNS can change).
"""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.round import Round
from app.models.platform_layer import Webhook, WebhookDelivery

log = logging.getLogger("launchpad.webhooks")

ACTION_TO_EVENT = {
    "team.create": "team.created",
    "team.join": "team.joined",
    "submission.create": "submission.created",
    "submission.replace": "submission.replaced",
    "submission.edit": "submission.updated",
    "submission.similar": "submission.flagged_similar",
    "round.close_early": "round.closed",
    "round.deadline_passed": "round.closed",
    "round.extend": "round.extended",
    "round.advance": "round.advanced",
    "results.publish": "results.published",
    "results.unpublish": "results.unpublished",
    "certificate.issue": "certificate.issued",
    "import.commit": "import.completed",
}
EVENT_TYPES = sorted(set(ACTION_TO_EVENT.values()) | {"webhook.test"})
MAX_FAILURES_BEFORE_DISABLE = 10


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def sign(secret: str, timestamp: int, body: str) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def _bad_ip(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


async def check_url(url: str) -> Optional[str]:
    """None when the URL is acceptable, else a human-readable reason."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "That isn't a valid URL."
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "Webhook URLs must start with http:// or https://."
    if parts.username or parts.password:
        return "Don't put credentials in the URL; use the signing secret instead."
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=0)
    except OSError:
        return f"Couldn't resolve the host '{parts.hostname}'."
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if _bad_ip(ip) and not settings.webhook_allow_private:
            return "That address is private or local. Webhooks to internal addresses are blocked (set WEBHOOK_ALLOW_PRIVATE=true to test locally)."
    return None


def _subscribed(hook: Webhook, etype: str) -> bool:
    return hook.events == "*" or etype in hook.events.split(",")


async def enqueue(db: AsyncSession, event_id: str, etype: str, row_id: str, created: datetime, data: dict[str, Any], only: Optional[str] = None) -> int:
    """Queue `etype` for every active, subscribed endpoint of the event."""
    stmt = select(Webhook).where(Webhook.event_id == event_id, Webhook.active.is_(True))
    if only:
        stmt = select(Webhook).where(Webhook.id == only)
    hooks = [h for h in (await db.execute(stmt)).scalars().all() if only or _subscribed(h, etype)]
    for h in hooks:
        payload = {"id": row_id, "type": etype, "created_at": created.isoformat(), "event_id": event_id, "data": data}
        db.add(WebhookDelivery(webhook_id=h.id, event_id=event_id, event_type=etype, payload=json.dumps(payload, default=str), next_attempt_at=datetime.now(timezone.utc)))
    return len(hooks)


async def enqueue_for_action(db: AsyncSession, event_id: str, row_id: str, action: str, target_type, target_id, detail: Optional[str], created: datetime) -> None:
    etype = ACTION_TO_EVENT.get(action)
    if etype is None:
        return
    try:
        parsed: Any = json.loads(detail) if detail else None
    except ValueError:
        parsed = detail
    await enqueue(db, event_id, etype, row_id, created, {"action": action, "target_type": target_type, "target_id": target_id, "detail": parsed})


def _delays() -> list[float]:
    return [float(x) for x in settings.webhook_retry_delays.split(",") if x.strip()]


async def _deliver(delivery_id: str) -> None:
    async with AsyncSessionLocal() as db:
        d = (await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id))).scalar_one_or_none()
        if d is None or d.status != "pending":
            return
        hook = (await db.execute(select(Webhook).where(Webhook.id == d.webhook_id))).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if hook is None or not hook.active:
            d.status, d.error = "failed", "endpoint disabled or deleted"
            await db.commit()
            return
        code: Optional[int] = None
        error: Optional[str] = None
        started = time.monotonic()
        try:
            problem = await check_url(hook.url)
            if problem:
                raise RuntimeError(problem)
            ts = int(time.time())
            async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds, follow_redirects=False) as client:
                resp = await client.post(
                    hook.url, content=d.payload,
                    headers={
                        "Content-Type": "application/json", "User-Agent": "Launchpad-Webhooks/1.0",
                        "X-Launchpad-Event": d.event_type, "X-Launchpad-Delivery": d.id,
                        "X-Launchpad-Signature": sign(hook.secret, ts, d.payload),
                    },
                )
            code = resp.status_code
            if not 200 <= code < 300:
                error = f"receiver answered HTTP {code}"
        except Exception as exc:  # noqa: BLE001 - any failure is just "not delivered"
            error = (str(exc) or exc.__class__.__name__)[:280]
        d.attempts += 1
        d.response_code = code
        d.duration_ms = int((time.monotonic() - started) * 1000)
        if error is None:
            d.status, d.error, d.delivered_at = "success", None, now
            hook.consecutive_failures = 0
        else:
            d.error = error
            delays = _delays()
            if d.attempts > len(delays):
                d.status = "failed"
                hook.consecutive_failures += 1
                if hook.consecutive_failures >= MAX_FAILURES_BEFORE_DISABLE:
                    hook.active, hook.disabled_reason = False, f"Disabled after {MAX_FAILURES_BEFORE_DISABLE} failed deliveries in a row."
            else:
                d.next_attempt_at = now + timedelta(seconds=delays[d.attempts - 1])
        await db.commit()


async def process_due(limit: int = 25) -> int:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        due = (await db.execute(
            select(WebhookDelivery.id, WebhookDelivery.next_attempt_at)
            .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
            .order_by(WebhookDelivery.next_attempt_at).limit(limit)
        )).all()
        claimed: list[str] = []
        for did, due_at in due:
            # Claim atomically so two workers never send the same delivery.
            res = await db.execute(
                update(WebhookDelivery).where(WebhookDelivery.id == did, WebhookDelivery.next_attempt_at == due_at, WebhookDelivery.status == "pending")
                .values(next_attempt_at=now + timedelta(seconds=max(30, settings.webhook_timeout_seconds * 3)))
            )
            if res.rowcount == 1:
                claimed.append(did)
        await db.commit()
    await asyncio.gather(*(_deliver(i) for i in claimed))
    return len(claimed)


async def sweep_round_deadlines() -> None:
    """A round closing because its deadline passed has no user action to
    hook, so notice it here and queue round.closed exactly once."""
    from app.services.audit import audit
    from app.services.rounds import round_state

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        rounds = (await db.execute(select(Round).where(Round.closed_notified_at.is_(None), Round.closes_at <= now))).scalars().all()
        changed = False
        for r in rounds:
            if round_state(r) == "closed":
                r.closed_notified_at = now
                await audit(db, "round.deadline_passed", event_id=r.event_id, actor_label="system", target_type="round", target_id=r.id, detail={"round": r.number, "name": r.name})
                changed = True
        if changed:
            await db.commit()


class Dispatcher:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await sweep_round_deadlines()
                await process_due()
                from app.services import mailer

                await mailer.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("webhook dispatcher tick failed")
            await asyncio.sleep(settings.webhook_poll_seconds)


dispatcher = Dispatcher()
