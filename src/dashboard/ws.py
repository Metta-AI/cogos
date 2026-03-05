from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, cogent_name: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(cogent_name, []).append(ws)

    def disconnect(self, cogent_name: str, ws: WebSocket):
        conns = self._connections.get(cogent_name, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, cogent_name: str, message: dict):
        payload = json.dumps(message, default=str)
        dead = []
        for ws in self._connections.get(cogent_name, []):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(cogent_name, ws)

    @property
    def connection_count(self) -> int:
        return sum(len(v) for v in self._connections.values())


manager = ConnectionManager()
