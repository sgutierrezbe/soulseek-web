"""soulseek-web -- a minimal web UI for slskd.

Run with:  uvicorn main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

import slskd
from auth import AuthMiddleware
from auth import router as auth_router
from config import BASE_DIR, CACHE_DIR, PLATFORM, settings
from routers import covers, downloads, library, search, setup, stats, stream
from stats import stats as upload_stats

STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Samples slskd's upload list so sharing totals survive slskd clearing its
    # own transfer history.
    poller = asyncio.create_task(stats.poller())
    try:
        yield
    finally:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(upload_stats.save, True)
        await slskd.close_clients()


app = FastAPI(
    title="Soulseek Web",
    version=settings.version,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(AuthMiddleware)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(setup.router, prefix="/api/setup", tags=["setup"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])
app.include_router(library.router, prefix="/api/library", tags=["library"])
app.include_router(covers.router, prefix="/api/covers", tags=["covers"])
app.include_router(stream.router, prefix="/api/stream", tags=["stream"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])


@app.exception_handler(slskd.SlskdError)
async def slskd_error_handler(request: Request, exc: slskd.SlskdError):
    return JSONResponse({"detail": exc.message}, status_code=502)


class CachedStaticFiles(StaticFiles):
    """Static assets with a short max-age; ETag handles revalidation after that."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
        return response


app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", include_in_schema=False)
async def index(request: Request):
    # Inlining the initial state saves the client two round trips before it can
    # decide between the login screen, the setup wizard, and the app itself.
    boot = {
        "configured": settings.configured,
        "local_setup": settings.local_setup,
        "platform": PLATFORM,
        "lang": settings.lang,
        "advanced_search": settings.advanced_search,
        "auth_enabled": settings.auth_enabled,
        "music_path": settings.music_path,
        "slskd_url": settings.slskd_url,
        "version": settings.version,
    }
    return templates.TemplateResponse(
        request,
        "index.html",
        {"boot": json.dumps(boot), "version": settings.version},
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health", include_in_schema=False)
async def health():
    payload = {
        "status": "ok",
        "version": settings.version,
        "platform": PLATFORM,
        "configured": settings.configured,
    }
    try:
        await slskd.ping()
        payload["slskd"] = "ok"
    except slskd.SlskdError as exc:
        payload["slskd"] = "unreachable"
        payload["slskd_error"] = exc.message
    return payload


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(
        STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    # Must be served from the root so it can control the whole origin, and must
    # not be cached or clients get stuck on an old worker.
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "favicon.ico")
