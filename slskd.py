"""Async client for the slskd REST API.

One `httpx.AsyncClient` is reused for every call so connections are pooled
instead of being renegotiated per request -- the old code built a fresh client
(and TLS session) for every search poll and every cover fetch. The API key and
base URL are read from `settings` at call time, so reconfiguring the connection
in the Settings panel takes effect on the next request without a restart.
"""

from __future__ import annotations

import httpx

from config import settings

_LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=16)

_slskd: httpx.AsyncClient | None = None
_external: httpx.AsyncClient | None = None


class SlskdError(RuntimeError):
    """slskd is unreachable, rejected our key, or returned a server error."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def client() -> httpx.AsyncClient:
    global _slskd
    if _slskd is None or _slskd.is_closed:
        _slskd = httpx.AsyncClient(
            limits=_LIMITS,
            timeout=httpx.Timeout(15.0, connect=4.0),
        )
    return _slskd


def external_client() -> httpx.AsyncClient:
    """Client for third-party metadata APIs (Deezer, iTunes)."""
    global _external
    if _external is None or _external.is_closed:
        _external = httpx.AsyncClient(
            limits=_LIMITS,
            timeout=httpx.Timeout(8.0, connect=4.0),
            follow_redirects=True,
            headers={"User-Agent": "soulseek-web"},
        )
    return _external


async def close_clients() -> None:
    global _slskd, _external
    for existing in (_slskd, _external):
        if existing is not None and not existing.is_closed:
            await existing.aclose()
    _slskd = _external = None


async def request(method: str, path: str, *, timeout: float | None = None, **kwargs):
    """Call the slskd API, translating transport failures into `SlskdError`."""
    if not settings.slskd_api_key:
        raise SlskdError("slskd is not configured yet.")

    url = f"{settings.slskd_url}/api/v0/{path.lstrip('/')}"
    headers = {"X-API-Key": settings.slskd_api_key, **kwargs.pop("headers", {})}
    if timeout is not None:
        kwargs["timeout"] = timeout

    try:
        response = await client().request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise SlskdError(f"Could not reach slskd at {settings.slskd_url}: {exc}") from exc

    if response.status_code in (401, 403):
        raise SlskdError("slskd rejected the API key.", response.status_code)
    if response.status_code >= 500:
        raise SlskdError(
            f"slskd returned an error ({response.status_code}).", response.status_code
        )
    return response


async def get_json(path: str, *, default=None, timeout: float | None = None, **kwargs):
    """GET a JSON endpoint, returning `default` when the body is empty."""
    response = await request("GET", path, timeout=timeout, **kwargs)
    if response.status_code == 404 or not response.content:
        return default
    try:
        return response.json()
    except ValueError:
        return default


async def ping(url: str | None = None, api_key: str | None = None) -> dict:
    """Check a slskd instance is reachable. Returns its /application payload."""
    base = (url or settings.slskd_url).rstrip("/")
    key = api_key if api_key is not None else settings.slskd_api_key
    try:
        response = await client().get(
            f"{base}/api/v0/application",
            headers={"X-API-Key": key},
            timeout=5.0,
        )
    except httpx.HTTPError as exc:
        raise SlskdError(f"Could not reach slskd at {base}: {exc}") from exc

    if response.status_code in (401, 403):
        raise SlskdError("slskd rejected the API key. Check web.authentication.api_keys.")
    if response.status_code not in (200, 204):
        raise SlskdError(f"slskd responded with HTTP {response.status_code}.")
    try:
        return response.json() if response.content else {}
    except ValueError:
        return {}
