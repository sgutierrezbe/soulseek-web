"""Optional password protection.

Auth stays off by default so a LAN install remains frictionless. Setting a
password -- in the Settings panel, or via the `AUTH_PASSWORD` env var for Docker
-- turns it on: the API then requires a signed session cookie obtained from
POST /api/auth/login. The cookie carries only an expiry plus an HMAC over it, so
there is no server-side session store to keep in sync.
"""

from __future__ import annotations

import hmac
import time
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

COOKIE_NAME = "slskweb_session"
SESSION_SECONDS = 30 * 24 * 3600

# The app shell and its assets load without a session; the shell then renders the
# login screen based on /api/auth/status.
_PUBLIC_PATHS = {"/", "/health", "/manifest.webmanifest", "/sw.js", "/favicon.ico"}
_PUBLIC_PREFIXES = ("/static/", "/api/auth/")


def _sign(expiry: int) -> str:
    return hmac.new(
        settings.session_secret.encode("utf-8"), str(expiry).encode("ascii"), sha256
    ).hexdigest()


def issue_token() -> str:
    expiry = int(time.time()) + SESSION_SECONDS
    return f"{expiry}.{_sign(expiry)}"


def token_is_valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    raw_expiry, _, signature = token.partition(".")
    try:
        expiry = int(raw_expiry)
    except ValueError:
        return False
    if expiry < time.time():
        return False
    return hmac.compare_digest(signature, _sign(expiry))


def request_is_authenticated(request: Request) -> bool:
    if not settings.auth_enabled:
        return True
    return token_is_valid(request.cookies.get(COOKIE_NAME))


def _set_cookie(response: Response, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        # Only mark Secure when actually served over TLS -- a Secure cookie on a
        # plain-http LAN address is silently dropped by the browser.
        secure=request.url.scheme == "https",
        path="/",
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated API calls once a password has been set."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            not settings.auth_enabled
            or path in _PUBLIC_PATHS
            or path.startswith(_PUBLIC_PREFIXES)
            or request_is_authenticated(request)
        ):
            return await call_next(request)
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Authentication required."}, status_code=401)


router = APIRouter()


class LoginRequest(BaseModel):
    password: str


class PasswordRequest(BaseModel):
    password: str = Field(default="", description="Empty string disables auth.")


@router.get("/status")
async def auth_status(request: Request):
    return {
        "enabled": settings.auth_enabled,
        "authenticated": request_is_authenticated(request),
        # A password set through the env var can't be cleared from the UI.
        "managed_by_env": settings.auth_from_env,
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    if not settings.auth_enabled:
        return {"ok": True, "enabled": False}
    if not settings.check_password(body.password):
        # Blunt the speed of online guessing without blocking the event loop.
        import asyncio

        await asyncio.sleep(1.0)
        raise HTTPException(401, "Incorrect password.")
    _set_cookie(response, request)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/password")
async def set_password(body: PasswordRequest, request: Request, response: Response):
    """Set, change, or (with an empty password) disable authentication."""
    if settings.auth_enabled and not request_is_authenticated(request):
        raise HTTPException(401, "Authentication required.")
    if settings.auth_from_env:
        raise HTTPException(
            400, "The password is set through the AUTH_PASSWORD environment variable."
        )

    password = body.password.strip()
    if password and len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")

    settings.set_password(password)
    if password:
        _set_cookie(response, request)
    else:
        response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "enabled": bool(password)}
