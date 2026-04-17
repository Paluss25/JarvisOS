"""JWT authentication — login, refresh, middleware, role enforcement."""

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from platform.audit import audit, AuditEvent
from platform.db import get_pool
from platform.models import LoginRequest, RefreshRequest, TokenResponse, UserProfile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

_security = HTTPBearer()

_ACCESS_TTL_MINUTES = 15
_REFRESH_TTL_DAYS = 7
_ALGORITHM = "HS256"


def _secret() -> str:
    s = os.environ.get("JARVIOS_JWT_SECRET", "")
    if not s:
        raise RuntimeError("JARVIOS_JWT_SECRET env var is not set")
    return s


def _create_token(payload: dict[str, Any], ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + ttl_seconds, "jti": str(uuid.uuid4())}
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# Dependency: get current user from Bearer token
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    payload = decode_access_token(credentials.credentials)
    return payload


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM users WHERE email = $1", req.email)
    if not row:
        await audit.log(AuditEvent(
            category="security",
            action="login_failed",
            source="api",
            detail={"email": req.email, "reason": "user_not_found"},
        ))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not bcrypt.checkpw(req.password.encode(), row["password"].encode()):
        await audit.log(AuditEvent(
            category="security",
            action="login_failed",
            source="api",
            user_id=str(row["id"]),
            detail={"email": req.email, "reason": "wrong_password"},
        ))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Update last_login
    await pool.execute(
        "UPDATE users SET last_login = NOW() WHERE id = $1", row["id"]
    )

    payload = {"sub": str(row["id"]), "email": row["email"], "role": row["role"], "name": row["name"]}
    access_token = _create_token(payload, _ACCESS_TTL_MINUTES * 60)
    refresh_token = _create_token({**payload, "type": "refresh"}, _REFRESH_TTL_DAYS * 86400)

    await audit.log(AuditEvent(
        category="security",
        action="login_success",
        source="api",
        user_id=str(row["id"]),
        detail={"email": row["email"], "role": row["role"]},
    ))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    try:
        payload = jwt.decode(req.refresh_token, _secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Not a refresh token")

    base = {k: v for k, v in payload.items() if k not in ("iat", "exp", "jti", "type")}
    access_token = _create_token(base, _ACCESS_TTL_MINUTES * 60)
    new_refresh = _create_token({**base, "type": "refresh"}, _REFRESH_TTL_DAYS * 86400)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh)


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserProfile)
async def me(user: dict = Depends(get_current_user)):
    return UserProfile(
        id=user["sub"],
        email=user["email"],
        name=user.get("name", ""),
        role=user.get("role", "viewer"),
    )
