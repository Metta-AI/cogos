"""GitHub outbound: post comments on issues and PRs."""
from __future__ import annotations

import aiohttp


class GitHubSender:
    def __init__(self, token: str):
        self._token = token
        self._session = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"token {self._token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "cogent",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def post_comment(self, repo, issue_number, body):
        session = await self._ensure_session()
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        async with session.post(url, json={"body": body}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
