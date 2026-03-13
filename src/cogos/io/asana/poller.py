"""Asana channel: polls for task assignments and comments."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from cogos.io.base import IOAdapter, IOMode, InboundEvent

logger = logging.getLogger(__name__)

BASE_URL = "https://app.asana.com/api/1.0"


class AsanaClient:
    def __init__(self, token: str):
        self.token = token
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        session = await self._ensure_session()
        async with session.get(f"{BASE_URL}{path}", params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, path: str, payload: dict) -> dict:
        session = await self._ensure_session()
        async with session.post(f"{BASE_URL}{path}", json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def me(self) -> dict[str, Any]:
        data = await self._get("/users/me")
        return data.get("data", {})

    async def get_workspaces(self) -> list[dict[str, Any]]:
        data = await self._get("/workspaces")
        return data.get("data", [])

    async def get_tasks(self, workspace_id: str, assignee: str) -> list[dict[str, Any]]:
        data = await self._get("/tasks", params={
            "workspace": workspace_id, "assignee": assignee,
            "opt_fields": "gid,name,notes,created_by.name,assignee.name,completed",
        })
        return data.get("data", [])

    async def get_task_stories(self, task_gid: str, since: str | None = None) -> list[dict]:
        params: dict[str, str] = {}
        if since:
            params["created_since"] = since
        data = await self._get(f"/tasks/{task_gid}/stories", params=params or None)
        return data.get("data", [])

    async def create_task(self, workspace_gid: str, name: str, *, notes: str = "",
                          assignee_gid: str | None = None, project_gid: str | None = None) -> dict[str, Any]:
        task_data: dict[str, Any] = {"workspace": workspace_gid, "name": name}
        if notes: task_data["notes"] = notes
        if assignee_gid: task_data["assignee"] = assignee_gid
        if project_gid: task_data["projects"] = [project_gid]
        data = await self._post("/tasks", {"data": task_data})
        return data.get("data", {})


class AsanaIO(IOAdapter):
    mode = IOMode.POLL

    def __init__(self, name: str = "asana", client: AsanaClient | None = None,
                 workspace_id: str | None = None, assignee_gid: str | None = None):
        super().__init__(name)
        self.client = client
        self.workspace_id = workspace_id
        self.assignee_gid = assignee_gid
        self._seen_task_gids: set[str] = set()
        self._pending_events: list[InboundEvent] = []

    async def poll(self) -> list[InboundEvent]:
        if self._pending_events:
            events = list(self._pending_events)
            self._pending_events.clear()
            return events
        if not self.client:
            return []
        if not self.workspace_id:
            try:
                workspaces = await self.client.get_workspaces()
                if workspaces:
                    self.workspace_id = workspaces[0]["gid"]
                else:
                    return []
            except Exception:
                logger.exception("Failed to discover Asana workspaces")
                return []
        if not self.assignee_gid:
            try:
                me = await self.client.me()
                self.assignee_gid = me.get("gid")
            except Exception:
                logger.exception("Failed to get Asana user info")
                return []
        events = []
        try:
            tasks = await self.client.get_tasks(self.workspace_id, self.assignee_gid or "me")
        except Exception:
            logger.exception("Failed to fetch Asana tasks")
            return []
        for task in tasks:
            gid = task.get("gid", "")
            if gid not in self._seen_task_gids:
                self._seen_task_gids.add(gid)
                event = InboundEvent(
                    channel="asana", message_type="task.assigned", payload=task,
                    raw_content=task.get("notes", ""),
                    author=task.get("created_by", {}).get("name", "human"),
                    external_id=f"asana:task:{gid}",
                    external_url=f"https://app.asana.com/0/0/{gid}",
                )
                events.append(event)
        return events

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
