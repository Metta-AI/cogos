from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
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
        alerts,
        capabilities,
        channels,
        cogos_status,
        cron,
        files,
        handlers,
        processes,
        resources,
        runs,
        schemas,
        setup,
        traces,
    )

    app.include_router(alerts.router, prefix="/api/cogents/{name}")
    app.include_router(processes.router, prefix="/api/cogents/{name}")
    app.include_router(handlers.router, prefix="/api/cogents/{name}")
    app.include_router(files.router, prefix="/api/cogents/{name}")
    app.include_router(capabilities.router, prefix="/api/cogents/{name}")
    app.include_router(channels.router, prefix="/api/cogents/{name}")
    app.include_router(schemas.router, prefix="/api/cogents/{name}")
    app.include_router(runs.router, prefix="/api/cogents/{name}")
    app.include_router(traces.router, prefix="/api/cogents/{name}")
    app.include_router(cogos_status.router, prefix="/api/cogents/{name}")
    app.include_router(cron.router, prefix="/api/cogents/{name}")
    app.include_router(resources.router, prefix="/api/cogents/{name}")
    app.include_router(setup.router, prefix="/api/cogents/{name}")

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

    # --- Web static content from FileStore (DB) ---
    @app.get("/web/static")
    async def web_static_root():
        from starlette.responses import RedirectResponse
        return RedirectResponse("/web/static/", status_code=301)

    @app.get("/web/static/{path:path}")
    async def web_static(path: str):
        import mimetypes

        from cogos.files.store import FileStore
        from dashboard.db import get_repo

        if not path or path.endswith("/"):
            path = (path or "") + "index.html"

        store = FileStore(get_repo())
        content = store.get_content(f"web/{path}")
        if content is None:
            return JSONResponse(status_code=404, content={"detail": "not found"})

        mime, _ = mimetypes.guess_type(path)
        return Response(content=content, media_type=mime or "application/octet-stream")

    # --- Executor proxy for web API requests ---
    @app.api_route("/web/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def web_api_proxy(request: Request, path: str):
        import asyncio
        import json
        from uuid import uuid4

        import boto3

        from cogos.db.models.channel_message import ChannelMessage
        from dashboard.db import get_repo

        repo = get_repo()
        channel = repo.get_channel_by_name("io:web:request")
        if not channel:
            return JSONResponse(status_code=503, content={"detail": "web request channel not configured"})

        handlers = repo.match_handlers_by_channel(channel.id)
        if not handlers:
            return JSONResponse(status_code=503, content={"detail": "no handler for web requests"})

        target_handler = handlers[0]
        process = repo.get_process(target_handler.process)
        if not process:
            return JSONResponse(status_code=503, content={"detail": "handler process not found"})

        request_id = str(uuid4())
        body = (await request.body()).decode() or None
        query_params = dict(request.query_params)
        headers = {k: v for k, v in request.headers.items() if not k.startswith("cf-")}

        msg = ChannelMessage(
            channel=channel.id,
            payload={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "query": query_params,
                "headers": headers,
                "body": body,
            },
        )
        repo.append_channel_message(msg)

        executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME", "")
        if not executor_fn:
            return JSONResponse(status_code=503, content={"detail": "executor function not configured"})

        def _invoke_executor() -> dict:
            lambda_client = boto3.client("lambda")
            response = lambda_client.invoke(
                FunctionName=executor_fn,
                InvocationType="RequestResponse",
                Payload=json.dumps(
                    {
                        "process_id": str(process.id),
                        "web_request_id": request_id,
                        "web_request": {
                            "method": request.method,
                            "path": path,
                            "query": query_params,
                            "headers": headers,
                            "body": body,
                        },
                    }
                ),
            )
            return json.loads(response["Payload"].read())

        try:
            resp_payload = await asyncio.to_thread(_invoke_executor)
            web_response = resp_payload.get("web_response")
            if not web_response:
                return Response(status_code=204)
            return Response(
                content=web_response.get("body", ""),
                status_code=web_response.get("status", 200),
                media_type=web_response.get("headers", {}).get("content-type", "application/json"),
            )
        except Exception:
            logger.exception("Executor invocation failed")
            return JSONResponse(status_code=502, content={"detail": "executor error"})

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
