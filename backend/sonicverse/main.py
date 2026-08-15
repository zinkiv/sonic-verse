"""SonicVerse FastAPI application."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from sonicverse.core.config import get_settings
from sonicverse.core.database import init_db
from sonicverse.core.http import close_http_client
from sonicverse.matcher.batch import reset_interrupted_match_jobs
from sonicverse.scanner.pipeline import reset_interrupted_jobs
from sonicverse.api.middleware import AuthGateMiddleware
from sonicverse.api.routes import (
    albums,
    artists,
    auth as auth_routes,
    matcher,
    scanner,
    settings as settings_routes,
    stats,
    tracks,
    upload,
)

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
    await reset_interrupted_jobs()
    await reset_interrupted_match_jobs()
    yield
    await close_http_client()


# Ensure runtime directories exist before the static mount below.
Path(settings.data_path).mkdir(parents=True, exist_ok=True)
Path(settings.covers_path).mkdir(parents=True, exist_ok=True)
Path(settings.library_path).mkdir(parents=True, exist_ok=True)
Path(settings.logs_path).mkdir(parents=True, exist_ok=True)
Path(settings.music_path).mkdir(parents=True, exist_ok=True)
Path(settings.transfer_path).mkdir(parents=True, exist_ok=True)

# Default SQLite lives under data/database/; create it only in that mode.
if settings.is_sqlite:
    sqlite_path = settings.sqlite_db_path
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    # One-time relocate: ./data/sonicverse.db or ./data/db/ → ./data/database/
    _new_db = sqlite_path
    _legacy_candidates = [
        Path(settings.data_path) / "sonicverse.db",
        Path(settings.data_path) / "db" / "sonicverse.db",
    ]
    if _new_db is not None and not _new_db.exists():
        for legacy_db in _legacy_candidates:
            if legacy_db.is_file():
                _new_db.parent.mkdir(parents=True, exist_ok=True)
                legacy_db.replace(_new_db)
                for suffix in ("-wal", "-shm"):
                    legacy_side = Path(f"{legacy_db}{suffix}")
                    if legacy_side.is_file():
                        legacy_side.replace(Path(f"{_new_db}{suffix}"))
                break

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Personal Digital Music Universe - Music metadata management and enhancement platform",
    lifespan=lifespan,
)

# CORS then auth gate (added last = runs first).
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CachedStaticFiles(StaticFiles):
    """Cover files are versioned with ``?v=``; let the browser keep them."""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        return response


# Serve cached cover images.
app.mount("/covers", CachedStaticFiles(directory=settings.covers_path), name="covers")

# Include routers
api_prefix = settings.api_prefix
app.include_router(auth_routes.router, prefix=api_prefix)
app.include_router(tracks.router, prefix=api_prefix)
app.include_router(matcher.router, prefix=api_prefix)
app.include_router(matcher.jobs_router, prefix=api_prefix)
app.include_router(albums.router, prefix=api_prefix)
app.include_router(artists.router, prefix=api_prefix)
app.include_router(scanner.router, prefix=api_prefix)
app.include_router(upload.router, prefix=api_prefix)
app.include_router(stats.router, prefix=api_prefix)
app.include_router(settings_routes.router, prefix=api_prefix)


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "version": settings.app_version}


def _mount_frontend(application: FastAPI) -> None:
    """Serve the Vue build from WEB_DIR when the Docker image includes it."""
    web_dir = Path(os.environ.get("WEB_DIR", "/app/web"))
    index = web_dir / "index.html"
    if not index.is_file():
        return

    assets = web_dir / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="web-assets")

    @application.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "covers/", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404, detail="Not Found")
        target = web_dir / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(index)


_mount_frontend(app)
