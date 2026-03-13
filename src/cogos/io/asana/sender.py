"""Asana outbound: create tasks and post comments."""

from __future__ import annotations

from cogos.io.asana.poller import AsanaClient


class AsanaSender:
    def __init__(self, client: AsanaClient):
        self._client = client

    async def create_task(self, workspace_gid: str, name: str, notes: str = "") -> dict:
        return await self._client.create_task(workspace_gid, name, notes=notes)

    async def post_comment(self, task_gid: str, text: str) -> dict:
        session = await self._client._ensure_session()
        async with session.post(
            f"https://app.asana.com/api/1.0/tasks/{task_gid}/stories",
            json={"data": {"text": text}},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()
