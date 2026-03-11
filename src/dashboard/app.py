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

_cached_admin_key: str | None = None


def _verify_admin_key(key: str) -> bool:
    """Check key against the dashboard API key stored in Secrets Manager."""
    global _cached_admin_key
    if _cached_admin_key is None:
        # Try env var first (set by CDK or task def), then Secrets Manager
        env_key = os.environ.get("DASHBOARD_API_KEY")
        if env_key:
            _cached_admin_key = env_key
        else:
            cogent_name = os.environ.get("COGENT_NAME", "")
            if cogent_name:
                try:
                    import json

                    import boto3
                    sm = boto3.client("secretsmanager", region_name="us-east-1")
                    secret_id = f"cogent/{cogent_name}/dashboard-api-key"
                    resp = sm.get_secret_value(SecretId=secret_id)
                    data = json.loads(resp["SecretString"])
                    _cached_admin_key = data.get("api_key", "")
                except Exception:
                    logger.warning("Could not load dashboard API key from Secrets Manager")
                    _cached_admin_key = ""
            else:
                _cached_admin_key = ""
    return bool(_cached_admin_key) and key == _cached_admin_key


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
        capabilities,
        cogos_events,
        cogos_status,
        cron,
        events,
        files,
        handlers,
        processes,
        runs,
    )
    app.include_router(processes.router, prefix="/api/cogents/{name}")
    app.include_router(handlers.router, prefix="/api/cogents/{name}")
    app.include_router(files.router, prefix="/api/cogents/{name}")
    app.include_router(capabilities.router, prefix="/api/cogents/{name}")
    app.include_router(runs.router, prefix="/api/cogents/{name}")
    app.include_router(cogos_events.router, prefix="/api/cogents/{name}")
    app.include_router(cogos_status.router, prefix="/api/cogents/{name}")
    app.include_router(events.router, prefix="/api/cogents/{name}")
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

    @app.post("/admin/reload-frontend")
    async def reload_frontend(request: Request) -> dict:
        """Signal the entrypoint to re-download frontend assets from S3 and restart Node."""
        import signal

        # Validate API key from header against Secrets Manager
        api_key = request.headers.get("x-api-key", "")
        if not api_key or not _verify_admin_key(api_key):
            return JSONResponse(status_code=403, content={"detail": "forbidden"})

        pid_file = Path("/tmp/entrypoint.pid")
        if not pid_file.exists():
            return JSONResponse(status_code=500, content={"ok": False, "error": "entrypoint PID file not found"})
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGUSR1)
        return {"ok": True, "message": "reload signal sent"}

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
