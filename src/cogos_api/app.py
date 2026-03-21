"""CogOS API — standalone capability proxy service.

Runs as a separate FastAPI service that remote executors authenticate to
via JWT tokens and use to invoke capabilities over HTTP.

Usage::

    uvicorn cogos_api.app:app --host 0.0.0.0 --port 8200
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cogos_api.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply CogOS SQL migrations on startup
    try:
        from cogos.db.migrations import apply_cogos_sql_migrations

        from cogos_api.db import get_repo

        repo = get_repo()
        statements = apply_cogos_sql_migrations(
            repo,
            on_error=lambda name, exc: logger.warning("Migration %s: %s", name, exc),
        )
        if statements:
            logger.info("Applied %d CogOS migration statements on startup", statements)
    except Exception:
        logger.warning("CogOS migrations failed on startup", exc_info=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="CogOS API",
        description="Secure capability proxy for remote executors",
        version="0.1.0",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from cogos_api.routers import capabilities, sessions

    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(capabilities.router, prefix="/api/v1")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "type": type(exc).__name__},
        )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app


app = create_app()
