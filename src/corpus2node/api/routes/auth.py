from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import current_principal
from corpus2node.accounts.models import AuthSession, User
from corpus2node.accounts.schemas import ActivateRequest, ChangePasswordRequest, CurrentUser, LoginRequest, Principal
from corpus2node.accounts.security import hash_password, verify_password
from corpus2node.accounts.service import (
    AuthenticationError,
    activate_invitation,
    authenticate,
    create_auth_session,
    current_user_view,
    revoke_auth_session,
)
from corpus2node.config import settings
from corpus2node.core.clock import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])
_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_WINDOW_SECONDS = 60.0
_MAX_ATTEMPTS = 10


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    attempts = _ATTEMPTS[key]
    while attempts and attempts[0] < now - _WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= _MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many authentication attempts. Try again later.")
    attempts.append(now)


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    max_age = settings.auth_session_days * 24 * 60 * 60
    response.set_cookie(
        "c2n_session",
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "c2n_csrf",
        csrf,
        max_age=max_age,
        httponly=False,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/activate", response_model=CurrentUser)
async def activate(
    payload: ActivateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    _check_rate_limit(f"activate:{request.client.host if request.client else 'unknown'}")
    try:
        user = await activate_invitation(
            db,
            token=payload.token,
            display_name=payload.display_name,
            password=payload.password,
        )
        _, token, csrf = await create_auth_session(db, user.user_id)
        await db.commit()
    except AuthenticationError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_session_cookies(response, token, csrf)
    principal = await _principal_for_new_session(db, token)
    return await current_user_view(db, principal)


@router.post("/login", response_model=CurrentUser)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    host = request.client.host if request.client else "unknown"
    _check_rate_limit(f"login:{host}:{str(payload.email).casefold()}")
    try:
        user = await authenticate(db, str(payload.email), payload.password)
        _, token, csrf = await create_auth_session(db, user.user_id)
        await db.commit()
    except AuthenticationError as exc:
        await db.rollback()
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookies(response, token, csrf)
    principal = await _principal_for_new_session(db, token)
    return await current_user_view(db, principal)


async def _principal_for_new_session(db: AsyncSession, token: str) -> Principal:
    from corpus2node.accounts.service import resolve_principal

    principal = await resolve_principal(db, token, None)
    if principal is None:
        raise HTTPException(status_code=500, detail="Unable to create authenticated session.")
    return principal


@router.get("/me", response_model=CurrentUser)
async def me(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    return await current_user_view(db, principal)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    _: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    await revoke_auth_session(db, request.cookies.get("c2n_session", ""))
    await db.commit()
    response.delete_cookie("c2n_session", path="/")
    response.delete_cookie("c2n_csrf", path="/")
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    user = await db.get(User, principal.user_id)
    if user is None or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = utcnow()
    current_hash = request.cookies.get("c2n_session", "")
    from corpus2node.accounts.security import hash_token

    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.user_id, AuthSession.token_hash != hash_token(current_hash))
        .values(revoked_at=utcnow())
    )
    await db.commit()
    return {"ok": True}
