from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from datetime import datetime, timezone

from app.models.invite import RoleInvite
from app.models.user import User, UserRole
from app.services.audit import audit
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists.",
        )

    invite = None
    if payload.role == UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The admin role can't be self-registered.")
    if payload.role in (UserRole.JUDGE, UserRole.ORGANIZER):
        # Judges and organizers need an invite code, so nobody can simply
        # tick "organizer" on the sign-up form. Same message for every
        # failure (unknown, wrong role, used up, expired, revoked).
        refusal = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"A valid invite code is required to register as {payload.role.value}.",
        )
        if not payload.invite_code:
            raise refusal
        invite = (
            await db.execute(select(RoleInvite).where(RoleInvite.code == payload.invite_code.strip()))
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        expired = invite is not None and invite.expires_at is not None and (
            invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
        ) <= now
        if (
            invite is None
            or invite.role != payload.role
            or invite.revoked_at is not None
            or invite.used_count >= invite.max_uses
            or expired
        ):
            raise refusal
        invite.used_count += 1

    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.flush()
    if invite is not None:
        await audit(
            db, "invite.used", event_id=invite.event_id, actor_label=f"{user.name} <{user.email}>",
            target_type="invite", target_id=invite.id, detail={"role": user.role.value},
        )
    # Welcome email, queued in the same transaction as the account itself.
    from app.services import mailer

    event_name = None
    if invite is not None and invite.event_id:
        from app.models.event import Event

        ev = (await db.execute(select(Event).where(Event.id == invite.event_id))).scalar_one_or_none()
        event_name = ev.name if ev else None
    try:
        async with db.begin_nested():
            await mailer.queue_welcome(db, user, event_name)
    except Exception:  # noqa: BLE001 -- an email problem must never block sign-up
        pass
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        # Same message either way -- never reveal whether the email exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    token = create_access_token(user.id, user.role.value)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)
