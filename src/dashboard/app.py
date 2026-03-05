from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from dashboard.config import settings
from dashboard.database import close_pool, get_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


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
        events,
        memory,
        programs,
        resources,
        sessions,
        status,
        tasks,
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
    app.include_router(memory.router, prefix="/api/cogents/{name}")

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

    return app


app = create_app()
