from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dashboard.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Cogent Dashboard API", version="0.1.0", lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if "*" in origins else origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from dashboard.routers import (
        alerts,
        channels,
        cron,
        events,
        memory,
        programs,
        resources,
        sessions,
        status,
        tasks,
        tools,
        triggers,
    )

    app.include_router(status.router, prefix="/api/cogents/{name}")
    app.include_router(programs.router, prefix="/api/cogents/{name}")
    app.include_router(sessions.router, prefix="/api/cogents/{name}")
    app.include_router(tasks.router, prefix="/api/cogents/{name}")
    app.include_router(channels.router, prefix="/api/cogents/{name}")
    app.include_router(alerts.router, prefix="/api/cogents/{name}")
    app.include_router(resources.router, prefix="/api/cogents/{name}")
    app.include_router(events.router, prefix="/api/cogents/{name}")
    app.include_router(triggers.router, prefix="/api/cogents/{name}")
    app.include_router(tools.router, prefix="/api/cogents/{name}")
    app.include_router(memory.router, prefix="/api/cogents/{name}")
    app.include_router(cron.router, prefix="/api/cogents/{name}")

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

    from dashboard.ws import manager

    @app.websocket("/ws/cogents/{name}")
    async def ws_endpoint(ws: WebSocket, name: str):
        await manager.connect(name, ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(name, ws)

    # Serve static frontend files if DASHBOARD_STATIC_DIR is set
    static_dir = os.environ.get("DASHBOARD_STATIC_DIR")
    if static_dir and Path(static_dir).is_dir():
        index_html = Path(static_dir) / "index.html"

        # Serve static assets (JS, CSS, images)
        app.mount("/_next", StaticFiles(directory=str(Path(static_dir) / "_next")), name="next-static")

        # SPA fallback: serve index.html for any non-API route
        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # Try to serve the exact file first (e.g. favicon.ico)
            file_path = Path(static_dir) / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(index_html))

    return app


app = create_app()
