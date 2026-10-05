"""API keys: let scripts and integrations use the platform's REST API.

A key is scoped to ONE event and is `read` (GET only) or `write`. It acts as
the organizer who created it, but can never reach account-level routes
(invites, other events, creating events) and can't mint further keys.
Only a SHA-256 of the key is stored; it is displayed once, at creation.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.ownership import get_owned_event
from app.core.security import API_KEY_PREFIX, hash_api_key, require_role
from app.models.platform_layer import ApiKey
from app.models.user import User, UserRole
from app.services.audit import audit

router = APIRouter()
Organizer = Depends(require_role(UserRole.ORGANIZER, UserRole.ADMIN))
MAX_KEYS = 20


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["read", "write"] = "read"
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365)


class KeyOut(BaseModel):
    id: str
    name: str
    scope: str
    prefix: str
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    revoked: bool
    key: Optional[str] = None  # only in the creation response


def _out(k: ApiKey, secret: Optional[str] = None) -> KeyOut:
    return KeyOut(id=k.id, name=k.name, scope=k.scope, prefix=k.prefix, created_at=k.created_at, expires_at=k.expires_at,
                  last_used_at=k.last_used_at, revoked=k.revoked_at is not None, key=secret)


def _no_keys(user: User) -> None:
    if getattr(user, "api_key_event_id", None) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "An API key can't manage API keys. Sign in as the organizer.")


@router.post("/events/{event_id}/api-keys", response_model=KeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(event_id: str, payload: KeyCreate, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    _no_keys(organizer)
    await get_owned_event(db, event_id, organizer)
    live = (await db.execute(select(ApiKey).where(ApiKey.event_id == event_id, ApiKey.revoked_at.is_(None)))).scalars().all()
    if len(live) >= MAX_KEYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"An event can have at most {MAX_KEYS} active API keys. Revoke one first.")
    secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(event_id=event_id, user_id=organizer.id, name=payload.name.strip(), scope=payload.scope, prefix=secret[:12], key_hash=hash_api_key(secret),
                 expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None)
    db.add(key)
    await db.flush()
    await audit(db, "apikey.create", event_id=event_id, actor=organizer, target_type="api_key", target_id=key.id, detail={"name": key.name, "scope": key.scope})
    await db.commit()
    await db.refresh(key)
    return _out(key, secret)


@router.get("/events/{event_id}/api-keys", response_model=list[KeyOut])
async def list_keys(event_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    _no_keys(organizer)
    await get_owned_event(db, event_id, organizer)
    keys = (await db.execute(select(ApiKey).where(ApiKey.event_id == event_id).order_by(ApiKey.created_at.desc()))).scalars().all()
    return [_out(k) for k in keys]


@router.delete("/events/{event_id}/api-keys/{key_id}", response_model=KeyOut)
async def revoke_key(event_id: str, key_id: str, db: AsyncSession = Depends(get_db), organizer: User = Organizer):
    _no_keys(organizer)
    await get_owned_event(db, event_id, organizer)
    key = (await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.event_id == event_id))).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found.")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await audit(db, "apikey.revoke", event_id=event_id, actor=organizer, target_type="api_key", target_id=key.id, detail={"name": key.name})
        await db.commit()
    return _out(key)
