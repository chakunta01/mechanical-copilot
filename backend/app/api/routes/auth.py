"""Auth routes: register, login, refresh, profile."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import RefreshToken, Role, User
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, db: DbSession) -> TokenOut:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise Conflict("Email already registered")

    # First user ever becomes admin; the rest are engineers.
    is_first = db.scalar(select(User.id).limit(1)) is None
    user = User(
        id=f"usr_{uuid.uuid4().hex[:20]}",
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=Role.ADMIN if is_first else Role.ENGINEER,
    )
    db.add(user)
    db.flush()

    access, _ = create_access_token(user.id, user.role.value)
    refresh, jti = create_refresh_token(user.id, user.role.value)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + __import__("datetime").timedelta(days=7),
        )
    )
    return TokenOut(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: DbSession) -> TokenOut:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise Unauthorized("Invalid email or password")
    if not user.is_active:
        raise Unauthorized("Account disabled")

    access, _ = create_access_token(user.id, user.role.value)
    refresh, jti = create_refresh_token(user.id, user.role.value)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + __import__("datetime").timedelta(days=7),
        )
    )
    return TokenOut(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshIn, db: DbSession) -> TokenOut:
    claims = decode_token(payload.refresh_token, expected_type="refresh")
    stored = db.get(RefreshToken, claims["jti"])
    if stored is None or stored.revoked:
        raise Unauthorized("Refresh token revoked")
    stored.revoked = True  # rotation: one-time use

    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise Unauthorized("User inactive or deleted")

    access, _ = create_access_token(user.id, user.role.value)
    new_refresh, jti = create_refresh_token(user.id, user.role.value)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=datetime.now(UTC).replace(tzinfo=None) + __import__("datetime").timedelta(days=7),
        )
    )
    return TokenOut(access_token=access, refresh_token=new_refresh)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
