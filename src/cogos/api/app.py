"""CogOS API — unified API service for dashboard and executor proxy.

Serves both the dashboard frontend API (under /api/cogents/{name}) and the
executor capability proxy (under /api/v1).

Usage::

    uvicorn cogos.api.app:app --host 0.0.0.0 --port 8200
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cogos.api.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm auth (Secrets Manager) — safe to run in each worker
    try:
        from dashboard.auth import _load_api_key

        _load_api_key()
        logger.info("Dashboard API key loaded")
    except Exception:
        logger.warning("Dashboard API key pre-warm failed", exc_info=True)

    # Pre-warm DB connection — create client, skip migrations here
    # (migrations run from the dispatcher Lambda on boot, not the API server)
    try:
        from cogos.api.db import get_repo
        from cogos.db.migrations import apply_cogos_sql_migrations

        get_repo()
        logger.info("DB connection ready")
    except Exception:
        logger.warning("DB pre-warm failed", exc_info=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="CogOS API",
        description="Unified API for dashboard and executor proxy",
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

    # ── Executor proxy routers ───────────────────────────────────
    from cogos.api.routers import capabilities as api_capabilities

    app.include_router(api_capabilities.router, prefix="/api/v1")

    # ── Dashboard routers (API-key protected) ────────────────────
    from fastapi import Depends

    from dashboard.auth import verify_dashboard_api_key
    from dashboard.routers import (
        alerts,
        capabilities,
        channels,
        chat,
        cogos_status,
        cogtainer,
        cron,
        diagnostics,
        executors,
        files,
        handlers,
        ingest,
        integrations,
        memory,
        operations,
        processes,
        resources,
        runs,
        schemas,
        setup,
        trace_viewer,
        traces,
    )

    dash_deps = [Depends(verify_dashboard_api_key)]

    app.include_router(alerts.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(chat.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(processes.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(handlers.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(files.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(capabilities.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(channels.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(schemas.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(runs.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(traces.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(trace_viewer.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(cogos_status.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(cron.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(resources.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(operations.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(setup.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(diagnostics.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(integrations.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(memory.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(executors.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(ingest.router, prefix="/api/cogents/{name}", dependencies=dash_deps)
    app.include_router(cogtainer.router, dependencies=dash_deps)

    # ── Common endpoints ───────────────────────────────────────

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

    @app.get("/api/version")
    async def api_version() -> dict:
        """Return component versions from the boot manifest and API metadata."""
        from cogos.api.db import get_repo

        # Load boot manifest from FileStore
        components: dict = {}
        booted_at = None
        epoch = None
        try:
            repo = get_repo()
            row = repo.get_file("mnt/boot/versions.json")
            if row:
                import json as _json

                manifest = _json.loads(row.content)
                components = manifest.get("components", {})
                booted_at = manifest.get("booted_at")
                epoch = manifest.get("epoch")
        except Exception:
            pass

        return {
            "components": components,
            "booted_at": booted_at,
            "epoch": epoch,
        }

    # ── WebSocket ──────────────────────────────────────────────

    from dashboard.ws import manager

    @app.websocket("/ws/cogents/{name}")
    async def ws_endpoint(ws: WebSocket, name: str):
        await manager.connect(name, ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(name, ws)

    # ── Web static content from FileStore (DB) ─────────────────

    def _serve_web_file(path: str) -> Response:
        from cogos.api.db import get_repo
        from cogos.files.store import FileStore
        from cogos.io.web.serving import lookup_static_file

        store = FileStore(get_repo())
        web_file = lookup_static_file(store, path)
        if web_file is None:
            return JSONResponse(status_code=404, content={"detail": "not found"})

        body: str | bytes = web_file.content
        if web_file.is_base64:
            try:
                body = base64.b64decode(web_file.content, validate=True)
            except (binascii.Error, ValueError):
                logger.warning("Invalid base64 web content for %s", web_file.key)
                return JSONResponse(status_code=500, content={"detail": "invalid published content"})

        return Response(content=body, media_type=web_file.content_type)

    @app.get("/web/static")
    async def web_static_root():
        return _serve_web_file("index.html")

    @app.get("/web/static/{path:path}")
    async def web_static(path: str):
        return _serve_web_file(path)

    # ── Blob content serving ───────────────────────────────────

    @app.get("/web/blobs/{path:path}")
    async def web_blob(path: str):
        """Serve blob content from S3 — used for AI-generated images in websites."""
        import boto3

        from cogos import get_sessions_bucket, get_sessions_prefix
        bucket = get_sessions_bucket()
        if not bucket:
            return JSONResponse(status_code=503, content={"detail": "blob storage not configured"})
        key = path if path.startswith("blobs/") else f"blobs/{path}"
        pfx = get_sessions_prefix()
        if pfx:
            key = f"{pfx}/{key}"
        try:
            s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            obj = s3.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            content_type = obj.get("ContentType", "application/octet-stream")
            return Response(
                content=body,
                media_type=content_type,
                headers={"cache-control": "public, max-age=86400"},
            )
        except Exception:
            logger.debug("Blob not found: %s", key, exc_info=True)
            return JSONResponse(status_code=404, content={"detail": "blob not found"})

    # ── Executor proxy for web API requests ────────────────────

    @app.api_route("/web/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def web_api_proxy(request: Request, path: str):
        import asyncio
        import json
        from uuid import uuid4

        import boto3

        from cogos.api.db import get_repo
        from cogos.db.models.channel_message import ChannelMessage

        repo = get_repo()
        channel = repo.get_channel_by_name("io:web:request")
        if not channel:
            return JSONResponse(status_code=503, content={"detail": "web request channel not configured"})

        handlers_list = repo.match_handlers_by_channel(channel.id)
        if not handlers_list:
            return JSONResponse(status_code=503, content={"detail": "no handler for web requests"})

        target_handler = handlers_list[0]
        process = repo.get_process(target_handler.process)
        if not process:
            return JSONResponse(status_code=503, content={"detail": "handler process not found"})

        request_id = str(uuid4())
        body = (await request.body()).decode() or None
        query_params = dict(request.query_params)
        headers_dict = {k: v for k, v in request.headers.items() if not k.startswith("cf-")}

        msg = ChannelMessage(
            channel=channel.id,
            payload={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "query": query_params,
                "headers": headers_dict,
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
                            "headers": headers_dict,
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

    # ── MCP server — auto-expose all endpoints as tools ────────
    # Must be mounted BEFORE the SPA catch-all route below.
    try:
        from fastapi_mcp import FastApiMCP

        mcp = FastApiMCP(app, name="cogos")
        mcp.mount_http(mount_path="/api/mcp")
        logger.info("FastAPI-MCP mounted at /api/mcp")
    except Exception:
        logger.warning("fastapi-mcp setup failed", exc_info=True)

    # ── Static frontend files ──────────────────────────────────

    static_dir = os.environ.get("DASHBOARD_STATIC_DIR")
    if static_dir and Path(static_dir).is_dir():
        index_html = Path(static_dir) / "index.html"

        app.mount("/_next", StaticFiles(directory=str(Path(static_dir) / "_next")), name="next-static")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            file_path = Path(static_dir) / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(index_html))

    return app


app = create_app()
