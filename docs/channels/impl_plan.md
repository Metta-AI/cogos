# Channels Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the channels package from cogents.0 into cogents.2 as pure IO (no classification, sanitization, or backpressure), restructured into per-channel subdirectories, with a new Google Calendar channel.

**Architecture:** Each channel is a subdirectory with its own listener/poller/webhook + optional sender. A `Channel` ABC in `base.py` defines the interface with three modes: live, poll, on-demand. Token management via AWS Secrets Manager with env var fallback. CLI for provisioning.

**Tech Stack:** Python 3.12, asyncio, discord.py, aiohttp, google-api-python-client, click, boto3, pytest

---

### Task 1: Base abstractions — `src/channels/base.py`

**Files:**
- Create: `src/channels/__init__.py`
- Create: `src/channels/base.py`
- Test: `tests/channels/__init__.py`
- Test: `tests/channels/test_base.py`

**Step 1: Write the failing test**

```python
# tests/channels/__init__.py
# (empty)
```

```python
# tests/channels/test_base.py
from channels.base import Channel, ChannelMode, InboundEvent
from datetime import datetime, timezone


class TestInboundEvent:
    def test_create_minimal(self):
        event = InboundEvent(channel="discord", event_type="dm", payload={}, raw_content="hello")
        assert event.channel == "discord"
        assert event.event_type == "dm"
        assert event.author is None

    def test_create_full(self):
        now = datetime.now(timezone.utc)
        event = InboundEvent(
            channel="github",
            event_type="push",
            payload={"ref": "main"},
            raw_content="pushed to main",
            author="daveey",
            timestamp=now,
            external_id="github:push:123",
            external_url="https://github.com/org/repo/commit/abc",
        )
        assert event.payload == {"ref": "main"}
        assert event.author == "daveey"
        assert event.timestamp == now
        assert event.external_id == "github:push:123"


class TestChannelMode:
    def test_modes_exist(self):
        assert ChannelMode.LIVE.value == "live"
        assert ChannelMode.POLL.value == "poll"
        assert ChannelMode.ON_DEMAND.value == "on_demand"


class TestChannelABC:
    def test_cannot_instantiate_abstract(self):
        import pytest
        with pytest.raises(TypeError):
            Channel(name="test")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_base.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

```python
# src/channels/__init__.py
```

```python
# src/channels/base.py
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class ChannelMode(str, enum.Enum):
    LIVE = "live"
    POLL = "poll"
    ON_DEMAND = "on_demand"


@dataclass
class InboundEvent:
    channel: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""
    author: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    external_id: str | None = None
    external_url: str | None = None


class Channel(ABC):
    mode: ChannelMode
    name: str

    def __init__(self, name: str):
        self.name = name

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    @abstractmethod
    async def poll(self) -> list[InboundEvent]:
        ...

    async def send(self, message: str, target: str, **kwargs: Any) -> None:
        raise NotImplementedError(f"{self.name} does not support sending")
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/__init__.py src/channels/base.py tests/channels/__init__.py tests/channels/test_base.py
git commit -m "feat(channels): add base abstractions — Channel ABC, InboundEvent, ChannelMode"
```

---

### Task 2: Token management — `src/channels/access.py`

**Files:**
- Create: `src/channels/access.py`
- Test: `tests/channels/test_access.py`

**Step 1: Write the failing test**

```python
# tests/channels/test_access.py
import os
from unittest.mock import MagicMock, patch

from channels.access import get_channel_token, get_channel_secret


class TestGetChannelToken:
    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "test-token-123"}):
            token = get_channel_token("cogent-1", "discord")
            assert token == "test-token-123"

    def test_returns_none_when_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("channels.access._get_secrets_client") as mock_sm:
                mock_sm.return_value.get_secret_value.side_effect = Exception("not found")
                token = get_channel_token("cogent-1", "discord")
                assert token is None


class TestGetChannelSecret:
    def test_returns_secret_dict(self):
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": '{"type": "static", "access_token": "abc"}'
        }
        with patch("channels.access._get_secrets_client", return_value=mock_sm):
            secret = get_channel_secret("cogent-1", "discord")
            assert secret == {"type": "static", "access_token": "abc"}

    def test_returns_none_on_error(self):
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = Exception("boom")
        with patch("channels.access._get_secrets_client", return_value=mock_sm):
            secret = get_channel_secret("cogent-1", "discord")
            assert secret is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_access.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write minimal implementation**

```python
# src/channels/access.py
"""Channel token access: fetches tokens from AWS Secrets Manager with env var fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)


def _get_secrets_client(region: str | None = None):
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("secretsmanager", region_name=region)


def get_channel_token(cogent_id: str, channel: str) -> str | None:
    """Get a channel's access token.

    Checks env var <CHANNEL>_BOT_TOKEN first, then Secrets Manager.
    """
    env_key = f"{channel.upper()}_BOT_TOKEN"
    env_token = os.environ.get(env_key)
    if env_token:
        logger.info("Using %s from environment", env_key)
        return env_token

    try:
        sm = _get_secrets_client()
        secret_id = f"identity_service/{cogent_id}/{channel}"
        resp = sm.get_secret_value(SecretId=secret_id)
        data = json.loads(resp["SecretString"])
        return data.get("access_token")
    except Exception:
        logger.exception("Failed to fetch %s token from Secrets Manager", channel)
        return None


def get_channel_secret(cogent_id: str, channel: str) -> dict[str, Any] | None:
    """Get the full secret dict for a channel."""
    try:
        sm = _get_secrets_client()
        secret_id = f"identity_service/{cogent_id}/{channel}"
        resp = sm.get_secret_value(SecretId=secret_id)
        return json.loads(resp["SecretString"])
    except Exception:
        logger.exception("Failed to fetch %s secret from Secrets Manager", channel)
        return None
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_access.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/access.py tests/channels/test_access.py
git commit -m "feat(channels): add token management with Secrets Manager + env fallback"
```

---

### Task 3: Discord channel — `src/channels/discord/`

**Files:**
- Create: `src/channels/discord/__init__.py`
- Create: `src/channels/discord/listener.py`
- Create: `src/channels/discord/sender.py`
- Test: `tests/channels/test_discord.py`

**Step 1: Write the failing test**

```python
# tests/channels/test_discord.py
import pytest
from channels.base import ChannelMode, InboundEvent
from channels.discord import DiscordChannel


class TestDiscordChannel:
    def test_mode_is_live(self):
        ch = DiscordChannel(name="discord")
        assert ch.mode == ChannelMode.LIVE

    async def test_poll_returns_queued_events(self):
        ch = DiscordChannel(name="discord")
        event = InboundEvent(channel="discord", event_type="dm", payload={}, raw_content="hi")
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].event_type == "dm"

    async def test_poll_drains_queue(self):
        ch = DiscordChannel(name="discord")
        for i in range(3):
            ch.add_event(InboundEvent(channel="discord", event_type=f"event.{i}", payload={}))
        events = await ch.poll()
        assert len(events) == 3
        events = await ch.poll()
        assert len(events) == 0

    async def test_start_without_token_is_noop(self):
        ch = DiscordChannel(name="discord")
        await ch.start()  # should not raise
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_discord.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/channels/discord/__init__.py
from channels.discord.listener import DiscordChannel

__all__ = ["DiscordChannel"]
```

```python
# src/channels/discord/listener.py
"""Discord channel: live Gateway connection for DMs, mentions, and channel messages."""

from __future__ import annotations

import asyncio
import logging

import discord

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)


class DiscordChannel(Channel):
    mode = ChannelMode.LIVE

    def __init__(
        self,
        name: str = "discord",
        bot_token: str | None = None,
        on_event: callable | None = None,
    ):
        super().__init__(name)
        self.bot_token = bot_token
        self._on_event = on_event
        self._pending_events: list[InboundEvent] = []
        self._client: discord.Client | None = None
        self._gateway_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.bot_token:
            logger.warning("No Discord bot token — channel disabled")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.members = True

        self._client = discord.Client(intents=intents)

        async def on_ready():
            if self._client and self._client.user:
                logger.info("Discord connected as %s (id=%s)", self._client.user.name, self._client.user.id)

        async def on_message(message):
            await self._handle_message(message)

        self._client.event(on_ready)
        self._client.event(on_message)

        self._gateway_task = asyncio.create_task(
            self._client.start(self.bot_token),
            name="discord-gateway",
        )

    async def stop(self) -> None:
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._gateway_task:
            self._gateway_task.cancel()
            try:
                await self._gateway_task
            except asyncio.CancelledError:
                pass

    async def poll(self) -> list[InboundEvent]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    async def _handle_message(self, message: discord.Message) -> None:
        if self._client and message.author.id == self._client.user.id:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self._client and self._client.user and self._client.user.mentioned_in(message)

        if is_dm:
            event_type = "dm"
        elif is_mention:
            event_type = "mention"
        else:
            event_type = "channel.message"

        guild_id = message.guild.id if message.guild else "DM"

        event = InboundEvent(
            channel="discord",
            event_type=event_type,
            payload={
                "content": message.content,
                "author": str(message.author),
                "author_id": str(message.author.id),
                "channel_id": str(message.channel.id),
                "guild_id": str(guild_id),
                "message_id": str(message.id),
                "attachments": [a.url for a in message.attachments],
            },
            raw_content=message.content,
            author=str(message.author),
            external_id=f"discord:msg:{message.id}",
            external_url=message.jump_url,
        )

        if self._on_event:
            await self._on_event(event)
        else:
            self._pending_events.append(event)

    def add_event(self, event: InboundEvent) -> None:
        """Manually add an event (for testing)."""
        self._pending_events.append(event)
```

```python
# src/channels/discord/sender.py
"""Discord outbound: send messages, reactions, typing indicators."""

from __future__ import annotations

import asyncio

import discord


class DiscordSender:
    def __init__(self, client: discord.Client):
        self._client = client

    async def send_message(self, channel_id: int, content: str) -> None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)
        await channel.send(content)

    async def add_reaction(self, channel_id: int, message_id: int, emoji: str) -> None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.add_reaction(emoji)

    async def start_typing(self, channel_id: int) -> asyncio.Task:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)

        async def _keep_typing():
            try:
                async with channel.typing():
                    await asyncio.sleep(120)
            except asyncio.CancelledError:
                pass

        return asyncio.create_task(_keep_typing())
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_discord.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/discord/ tests/channels/test_discord.py
git commit -m "feat(channels): add Discord channel (live Gateway listener + sender)"
```

---

### Task 4: GitHub channel — `src/channels/github/`

**Files:**
- Create: `src/channels/github/__init__.py`
- Create: `src/channels/github/webhook.py`
- Create: `src/channels/github/sender.py`
- Test: `tests/channels/test_github.py`

**Step 1: Write the failing test**

```python
# tests/channels/test_github.py
import hashlib
import hmac

from channels.base import ChannelMode, InboundEvent
from channels.github import GitHubChannel
from channels.github.webhook import verify_signature


class TestGitHubSignature:
    def test_valid_signature(self):
        secret = "test-secret"
        payload = b'{"action":"opened"}'
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert verify_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        assert verify_signature(b"payload", "sha256=invalid", "secret") is False

    def test_missing_prefix(self):
        assert verify_signature(b"payload", "invalid", "secret") is False


class TestGitHubChannel:
    def test_mode_is_on_demand(self):
        ch = GitHubChannel(name="github")
        assert ch.mode == ChannelMode.ON_DEMAND

    async def test_poll_returns_queued_events(self):
        ch = GitHubChannel(name="github")
        event = InboundEvent(channel="github", event_type="push", payload={})
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].event_type == "push"

    async def test_poll_drains_queue(self):
        ch = GitHubChannel(name="github")
        for i in range(3):
            ch.add_event(InboundEvent(channel="github", event_type=f"event.{i}", payload={}))
        events = await ch.poll()
        assert len(events) == 3
        events = await ch.poll()
        assert len(events) == 0

    def test_ingest_webhook_payload(self):
        ch = GitHubChannel(name="github")
        event = ch.ingest_webhook(
            gh_event="issues",
            action="assigned",
            payload={
                "sender": {"login": "testuser"},
                "repository": {"full_name": "org/repo"},
                "issue": {"number": 42, "body": "Fix this", "html_url": "https://github.com/org/repo/issues/42"},
            },
        )
        assert event.event_type == "issue.assigned"
        assert event.author == "testuser"
        assert event.external_id == "github:issue:org/repo:42"

    def test_ingest_ci_failure(self):
        ch = GitHubChannel(name="github")
        event = ch.ingest_webhook(
            gh_event="check_suite",
            action="completed",
            payload={
                "sender": {"login": "github-actions"},
                "repository": {"full_name": "org/repo"},
                "conclusion": "failure",
            },
        )
        assert event.event_type == "ci.failure"

    def test_ingest_unknown_event(self):
        ch = GitHubChannel(name="github")
        event = ch.ingest_webhook(
            gh_event="unknown_event",
            action="triggered",
            payload={
                "sender": {"login": "bot"},
                "repository": {"full_name": "org/repo"},
            },
        )
        assert event.event_type == "github.unknown_event.triggered"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_github.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/channels/github/__init__.py
from channels.github.webhook import GitHubChannel

__all__ = ["GitHubChannel"]
```

```python
# src/channels/github/webhook.py
"""GitHub channel: on-demand webhook receiver with HMAC verification."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import logging

from aiohttp import web

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)

GITHUB_EVENT_MAP = {
    ("issues", "assigned"): "issue.assigned",
    ("issues", "opened"): "issue.opened",
    ("issues", "closed"): "issue.closed",
    ("issue_comment", "created"): "issue.comment",
    ("pull_request", "opened"): "pr.opened",
    ("pull_request", "closed"): "pr.closed",
    ("pull_request", "review_requested"): "pr.review_requested",
    ("pull_request_review", "submitted"): "pr.review",
    ("pull_request_review_comment", "created"): "pr.comment",
    ("check_suite", "completed"): "ci.completed",
    ("check_run", "completed"): "ci.check_completed",
    ("push", None): "push",
}


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = hmac_mod.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac_mod.compare_digest(signature[7:], expected)


class GitHubChannel(Channel):
    mode = ChannelMode.ON_DEMAND

    def __init__(
        self,
        name: str = "github",
        webhook_secret: str | None = None,
        watched_repos: list[str] | None = None,
    ):
        super().__init__(name)
        self.webhook_secret = webhook_secret
        self.watched_repos = set(watched_repos) if watched_repos else set()
        self._pending_events: list[InboundEvent] = []

    async def poll(self) -> list[InboundEvent]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def ingest_webhook(self, gh_event: str, action: str | None, payload: dict) -> InboundEvent:
        """Convert a raw GitHub webhook payload to an InboundEvent and queue it."""
        event_type = GITHUB_EVENT_MAP.get((gh_event, action), f"github.{gh_event}.{action}")

        sender = payload.get("sender", {}).get("login", "unknown")
        repo_name = payload.get("repository", {}).get("full_name", "")

        content = ""
        external_id = None
        external_url = None

        if gh_event in ("issues", "issue_comment"):
            issue = payload.get("issue", {})
            external_id = f"github:issue:{repo_name}:{issue.get('number')}"
            external_url = issue.get("html_url")
            if gh_event == "issue_comment":
                comment = payload.get("comment", {})
                content = comment.get("body", "")
                external_url = comment.get("html_url", external_url)
            else:
                content = issue.get("body", "")

        elif gh_event in ("pull_request", "pull_request_review", "pull_request_review_comment"):
            pr = payload.get("pull_request", {})
            external_id = f"github:pr:{repo_name}:{pr.get('number')}"
            external_url = pr.get("html_url")
            if gh_event == "pull_request_review_comment":
                comment = payload.get("comment", {})
                content = comment.get("body", "")
                external_url = comment.get("html_url", external_url)
            elif gh_event == "pull_request_review":
                review = payload.get("review", {})
                content = review.get("body", "")
            else:
                content = pr.get("body", "")

        elif gh_event in ("check_suite", "check_run"):
            conclusion = payload.get("conclusion", "")
            content = f"CI {gh_event}: {conclusion}"
            if conclusion == "failure":
                event_type = "ci.failure"

        event = InboundEvent(
            channel="github",
            event_type=event_type,
            payload=payload,
            raw_content=content or "",
            author=sender,
            external_id=external_id,
            external_url=external_url,
        )
        self._pending_events.append(event)
        return event

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """aiohttp handler for GitHub webhook POST requests."""
        body = await request.read()

        if self.webhook_secret:
            sig = request.headers.get("X-Hub-Signature-256", "")
            if not verify_signature(body, sig, self.webhook_secret):
                return web.Response(status=403, text="Invalid signature")

        gh_event = request.headers.get("X-GitHub-Event", "")
        if gh_event == "ping":
            return web.Response(text="pong")

        try:
            payload = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        action = payload.get("action")
        repo_name = payload.get("repository", {}).get("full_name", "")

        if self.watched_repos and repo_name not in self.watched_repos:
            return web.Response(text="ignored")

        self.ingest_webhook(gh_event, action, payload)
        return web.Response(text="ok")

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
```

```python
# src/channels/github/sender.py
"""GitHub outbound: post comments on issues and PRs."""

from __future__ import annotations

import aiohttp


class GitHubSender:
    def __init__(self, token: str):
        self._token = token
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"token {self._token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "cogent",
                }
            )
        return self._session

    async def post_comment(self, repo: str, issue_number: int, body: str) -> dict:
        session = await self._ensure_session()
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        async with session.post(url, json={"body": body}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_github.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/github/ tests/channels/test_github.py
git commit -m "feat(channels): add GitHub channel (on-demand webhook + sender)"
```

---

### Task 5: Gmail channel — `src/channels/gmail/`

**Files:**
- Create: `src/channels/gmail/__init__.py`
- Create: `src/channels/gmail/poller.py`
- Create: `src/channels/gmail/sender.py`
- Test: `tests/channels/test_gmail.py`

**Step 1: Write the failing test**

```python
# tests/channels/test_gmail.py
from channels.base import ChannelMode, InboundEvent
from channels.gmail import GmailChannel


class TestGmailChannel:
    def test_mode_is_poll(self):
        ch = GmailChannel(name="gmail")
        assert ch.mode == ChannelMode.POLL

    async def test_poll_returns_queued_events(self):
        ch = GmailChannel(name="gmail")
        event = InboundEvent(
            channel="gmail",
            event_type="email.general",
            payload={"subject": "Hello"},
            raw_content="Hello body",
            author="human@example.com",
            external_id="gmail:msg-123",
        )
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].author == "human@example.com"

    async def test_poll_without_client_returns_empty(self):
        ch = GmailChannel(name="gmail")
        events = await ch.poll()
        assert len(events) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_gmail.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/channels/gmail/__init__.py
from channels.gmail.poller import GmailChannel, GmailClient

__all__ = ["GmailChannel", "GmailClient"]
```

```python
# src/channels/gmail/poller.py
"""Gmail channel: polls for new emails via Gmail API with service account credentials."""

from __future__ import annotations

import base64
import logging
from email.utils import parseaddr
from typing import Any

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)


class GmailClient:
    def __init__(self, service_account_key: dict, impersonate_email: str, scopes: list[str]):
        self._sa_key = service_account_key
        self._impersonate_email = impersonate_email
        self._scopes = scopes
        self._service: Any = None

    def _build_service(self) -> Any:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_info(
            self._sa_key, scopes=self._scopes, subject=self._impersonate_email,
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def get_profile(self) -> dict[str, Any]:
        svc = self._ensure_service()
        return svc.users().getProfile(userId="me").execute()

    def list_messages(self, query: str = "", max_results: int = 20) -> list[dict[str, str]]:
        svc = self._ensure_service()
        resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return resp.get("messages", [])

    def get_message(self, msg_id: str) -> dict[str, Any]:
        svc = self._ensure_service()
        return svc.users().messages().get(userId="me", id=msg_id, format="full").execute()

    def get_message_metadata(self, msg_id: str) -> dict[str, Any]:
        svc = self._ensure_service()
        return (
            svc.users().messages()
            .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"])
            .execute()
        )


def _extract_headers(msg: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for h in msg.get("payload", {}).get("headers", []):
        name = h.get("name", "").lower()
        if name in ("from", "to", "subject", "date", "message-id"):
            headers[name] = h.get("value", "")
    return headers


def _extract_body(msg: dict) -> str:
    payload = msg.get("payload", {})

    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            if sub.get("mimeType") == "text/plain" and sub.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(sub["body"]["data"]).decode("utf-8", errors="replace")

    return msg.get("snippet", "")


class GmailChannel(Channel):
    mode = ChannelMode.POLL

    def __init__(
        self,
        name: str = "gmail",
        client: GmailClient | None = None,
    ):
        super().__init__(name)
        self.client = client
        self._seen_msg_ids: set[str] = set()
        self._initialized = False
        self._pending_events: list[InboundEvent] = []

    async def poll(self) -> list[InboundEvent]:
        if self._pending_events:
            events = list(self._pending_events)
            self._pending_events.clear()
            return events

        if not self.client:
            return []

        if not self._initialized:
            try:
                existing = self.client.list_messages(query="is:inbox", max_results=50)
                self._seen_msg_ids = {m["id"] for m in existing}
                profile = self.client.get_profile()
                logger.info(
                    "Gmail connected as %s, seeded %d existing messages",
                    profile.get("emailAddress"), len(self._seen_msg_ids),
                )
                self._initialized = True
            except Exception:
                logger.exception("Failed to initialize Gmail channel")
                return []

        events: list[InboundEvent] = []

        try:
            messages = self.client.list_messages(query="is:inbox is:unread", max_results=20)
        except Exception:
            logger.exception("Failed to list Gmail messages")
            return []

        for stub in messages:
            msg_id = stub["id"]
            if msg_id in self._seen_msg_ids:
                continue
            self._seen_msg_ids.add(msg_id)

            try:
                msg = self.client.get_message(msg_id)
            except Exception:
                logger.exception("Failed to fetch message %s", msg_id)
                continue

            headers = _extract_headers(msg)
            subject = headers.get("subject", "(no subject)")
            sender = headers.get("from", "unknown")
            _, sender_email = parseaddr(sender)
            body = _extract_body(msg)
            message_id = headers.get("message-id", msg_id)

            event = InboundEvent(
                channel="gmail",
                event_type="email",
                payload={
                    "subject": subject,
                    "sender": sender,
                    "sender_email": sender_email,
                    "to": headers.get("to", ""),
                    "date": headers.get("date", ""),
                    "thread_id": stub.get("threadId", ""),
                    "message_id": msg_id,
                    "labels": msg.get("labelIds", []),
                },
                raw_content=body,
                author=sender,
                external_id=f"gmail:{message_id}",
            )
            events.append(event)

        return events

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
```

```python
# src/channels/gmail/sender.py
"""Gmail outbound: send emails via Gmail API."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any


class GmailSender:
    def __init__(self, client: Any):
        self._client = client

    def send_email(self, to: str, subject: str, body: str) -> dict:
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc = self._client._ensure_service()
        return svc.users().messages().send(userId="me", body={"raw": raw}).execute()
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_gmail.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/gmail/ tests/channels/test_gmail.py
git commit -m "feat(channels): add Gmail channel (poll via service account + sender)"
```

---

### Task 6: Asana channel — `src/channels/asana/`

**Files:**
- Create: `src/channels/asana/__init__.py`
- Create: `src/channels/asana/poller.py`
- Create: `src/channels/asana/sender.py`
- Test: `tests/channels/test_asana.py`

**Step 1: Write the failing test**

```python
# tests/channels/test_asana.py
from channels.base import ChannelMode, InboundEvent
from channels.asana import AsanaChannel


class TestAsanaChannel:
    def test_mode_is_poll(self):
        ch = AsanaChannel(name="asana")
        assert ch.mode == ChannelMode.POLL

    async def test_poll_returns_queued_events(self):
        ch = AsanaChannel(name="asana")
        event = InboundEvent(
            channel="asana",
            event_type="task.assigned",
            payload={"gid": "12345"},
            raw_content="Build the thing",
            author="human",
            external_id="asana:task:12345",
        )
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].author == "human"

    async def test_poll_without_client_returns_empty(self):
        ch = AsanaChannel(name="asana")
        events = await ch.poll()
        assert len(events) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_asana.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/channels/asana/__init__.py
from channels.asana.poller import AsanaChannel, AsanaClient

__all__ = ["AsanaChannel", "AsanaClient"]
```

```python
# src/channels/asana/poller.py
"""Asana channel: polls for task assignments and comments."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from channels.base import Channel, ChannelMode, InboundEvent

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
        data = await self._get(
            "/tasks",
            params={
                "workspace": workspace_id,
                "assignee": assignee,
                "opt_fields": "gid,name,notes,created_by.name,assignee.name,completed",
            },
        )
        return data.get("data", [])

    async def get_task_stories(self, task_gid: str, since: str | None = None) -> list[dict]:
        params: dict[str, str] = {}
        if since:
            params["created_since"] = since
        data = await self._get(f"/tasks/{task_gid}/stories", params=params or None)
        return data.get("data", [])

    async def create_task(
        self,
        workspace_gid: str,
        name: str,
        *,
        notes: str = "",
        assignee_gid: str | None = None,
        project_gid: str | None = None,
    ) -> dict[str, Any]:
        task_data: dict[str, Any] = {"workspace": workspace_gid, "name": name}
        if notes:
            task_data["notes"] = notes
        if assignee_gid:
            task_data["assignee"] = assignee_gid
        if project_gid:
            task_data["projects"] = [project_gid]
        data = await self._post("/tasks", {"data": task_data})
        return data.get("data", {})


class AsanaChannel(Channel):
    mode = ChannelMode.POLL

    def __init__(
        self,
        name: str = "asana",
        client: AsanaClient | None = None,
        workspace_id: str | None = None,
        assignee_gid: str | None = None,
    ):
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
                    channel="asana",
                    event_type="task.assigned",
                    payload=task,
                    raw_content=task.get("notes", ""),
                    author=task.get("created_by", {}).get("name", "human"),
                    external_id=f"asana:task:{gid}",
                    external_url=f"https://app.asana.com/0/0/{gid}",
                )
                events.append(event)

        return events

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
```

```python
# src/channels/asana/sender.py
"""Asana outbound: create tasks and post comments."""

from __future__ import annotations

from channels.asana.poller import AsanaClient


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
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_asana.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/asana/ tests/channels/test_asana.py
git commit -m "feat(channels): add Asana channel (poll for tasks + sender)"
```

---

### Task 7: Calendar channel — `src/channels/calendar/`

**Files:**
- Create: `src/channels/calendar/__init__.py`
- Create: `src/channels/calendar/poller.py`
- Test: `tests/channels/test_calendar.py`

**Step 1: Write the failing test**

```python
# tests/channels/test_calendar.py
from channels.base import ChannelMode, InboundEvent
from channels.calendar import CalendarChannel


class TestCalendarChannel:
    def test_mode_is_poll(self):
        ch = CalendarChannel(name="calendar")
        assert ch.mode == ChannelMode.POLL

    async def test_poll_returns_queued_events(self):
        ch = CalendarChannel(name="calendar")
        event = InboundEvent(
            channel="calendar",
            event_type="event.upcoming",
            payload={"summary": "Standup", "start": "2026-03-04T10:00:00Z"},
            raw_content="Standup",
        )
        ch.add_event(event)
        events = await ch.poll()
        assert len(events) == 1
        assert events[0].payload["summary"] == "Standup"

    async def test_poll_without_client_returns_empty(self):
        ch = CalendarChannel(name="calendar")
        events = await ch.poll()
        assert len(events) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_calendar.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/channels/calendar/__init__.py
from channels.calendar.poller import CalendarChannel, CalendarClient

__all__ = ["CalendarChannel", "CalendarClient"]
```

```python
# src/channels/calendar/poller.py
"""Google Calendar channel: polls for upcoming events via Calendar API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)


class CalendarClient:
    def __init__(self, service_account_key: dict, impersonate_email: str, scopes: list[str] | None = None):
        self._sa_key = service_account_key
        self._impersonate_email = impersonate_email
        self._scopes = scopes or [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ]
        self._service: Any = None

    def _build_service(self) -> Any:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_info(
            self._sa_key, scopes=self._scopes, subject=self._impersonate_email,
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def list_upcoming_events(
        self,
        calendar_id: str = "primary",
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        svc = self._ensure_service()
        now = datetime.now(timezone.utc)
        time_min = time_min or now
        time_max = time_max or now + timedelta(minutes=30)

        resp = (
            svc.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return resp.get("items", [])


class CalendarChannel(Channel):
    mode = ChannelMode.POLL

    def __init__(
        self,
        name: str = "calendar",
        client: CalendarClient | None = None,
        lookahead_minutes: int = 30,
    ):
        super().__init__(name)
        self.client = client
        self.lookahead_minutes = lookahead_minutes
        self._seen_event_ids: set[str] = set()
        self._pending_events: list[InboundEvent] = []

    async def poll(self) -> list[InboundEvent]:
        if self._pending_events:
            events = list(self._pending_events)
            self._pending_events.clear()
            return events

        if not self.client:
            return []

        now = datetime.now(timezone.utc)
        time_max = now + timedelta(minutes=self.lookahead_minutes)

        try:
            cal_events = self.client.list_upcoming_events(time_min=now, time_max=time_max)
        except Exception:
            logger.exception("Failed to list calendar events")
            return []

        events: list[InboundEvent] = []

        for cal_event in cal_events:
            event_id = cal_event.get("id", "")
            if event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event_id)

            summary = cal_event.get("summary", "(no title)")
            start = cal_event.get("start", {}).get("dateTime") or cal_event.get("start", {}).get("date", "")
            organizer = cal_event.get("organizer", {}).get("email", "")

            event = InboundEvent(
                channel="calendar",
                event_type="event.upcoming",
                payload={
                    "summary": summary,
                    "start": start,
                    "end": cal_event.get("end", {}).get("dateTime", ""),
                    "location": cal_event.get("location", ""),
                    "description": cal_event.get("description", ""),
                    "attendees": [a.get("email", "") for a in cal_event.get("attendees", [])],
                    "html_link": cal_event.get("htmlLink", ""),
                    "event_id": event_id,
                },
                raw_content=summary,
                author=organizer,
                external_id=f"calendar:{event_id}",
                external_url=cal_event.get("htmlLink"),
            )
            events.append(event)

        return events

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/test_calendar.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/channels/calendar/ tests/channels/test_calendar.py
git commit -m "feat(channels): add Google Calendar channel (poll for upcoming events)"
```

---

### Task 8: Setup guides

**Files:**
- Create: `src/channels/discord/guide.md`
- Create: `src/channels/github/guide.md`
- Create: `src/channels/gmail/guide.md`
- Create: `src/channels/asana/guide.md`
- Create: `src/channels/calendar/guide.md`

**Step 1: Copy guides from cogents.0**

Port the guides from `cogents.0/src/channels/guides/` into each channel's subdirectory. The `gmail/guide.md` is updated to include Calendar scopes. Create `calendar/guide.md` that references the Gmail guide (shared service account).

**Step 2: Commit**

```bash
git add src/channels/*/guide.md
git commit -m "docs(channels): add setup guides for all channels"
```

---

### Task 9: CLI — `src/channels/cli.py`

**Files:**
- Create: `src/channels/cli.py`

**Step 1: Port the CLI from cogents.0**

Port `cogents.0/src/channels/cli.py` with these changes:
- Rename `test` subcommand to `send`
- Add `calendar` to `CHANNEL_TYPES` as `service_account`
- Add `calendar` to `CHANNEL_GUIDES` (references gmail guide)
- Update guide loading to use `src/channels/<channel>/guide.md` paths
- Remove imports of `body.aws.AwsContext`, `cli.common.DefaultCommandGroup`, `polis.aws.get_polis_session` — these will need stubs or the actual implementations from other packages. For now, keep the imports but mark them with `# TODO: wire up when body/polis packages are ported`

**Step 2: Commit**

```bash
git add src/channels/cli.py
git commit -m "feat(channels): port CLI with list/create/destroy/status/logs/send commands"
```

---

### Task 10: Package wiring and integration test

**Files:**
- Modify: `src/channels/__init__.py`
- Modify: `pyproject.toml` (update packages list)
- Test: `tests/channels/test_integration.py`

**Step 1: Write the integration test**

```python
# tests/channels/test_integration.py
"""Verify all channels can be imported and instantiated."""

from channels.base import Channel, ChannelMode, InboundEvent
from channels.discord import DiscordChannel
from channels.github import GitHubChannel
from channels.gmail import GmailChannel
from channels.asana import AsanaChannel
from channels.calendar import CalendarChannel


class TestAllChannelsImport:
    def test_discord(self):
        ch = DiscordChannel()
        assert ch.mode == ChannelMode.LIVE
        assert isinstance(ch, Channel)

    def test_github(self):
        ch = GitHubChannel()
        assert ch.mode == ChannelMode.ON_DEMAND
        assert isinstance(ch, Channel)

    def test_gmail(self):
        ch = GmailChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

    def test_asana(self):
        ch = AsanaChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

    def test_calendar(self):
        ch = CalendarChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)
```

**Step 2: Update `__init__.py` with top-level exports**

```python
# src/channels/__init__.py
from channels.base import Channel, ChannelMode, InboundEvent

__all__ = ["Channel", "ChannelMode", "InboundEvent"]
```

**Step 3: Update pyproject.toml packages**

Replace the `packages` line to include channel subdirectories:

```toml
packages = [
    "src/cli", "src/body", "src/brain", "src/mind", "src/memory",
    "src/channels", "src/channels/discord", "src/channels/github",
    "src/channels/gmail", "src/channels/asana", "src/channels/calendar",
    "src/polis",
]
```

Also add Google API dependencies:

```toml
dependencies = [
    # ... existing ...
    "google-api-python-client>=2.100",
    "google-auth>=2.25",
]
```

**Step 4: Run all tests**

Run: `cd /Users/daveey/code/cogents/cogents.2 && uv run pytest tests/channels/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/channels/__init__.py pyproject.toml tests/channels/test_integration.py
git commit -m "feat(channels): wire up package exports and integration test"
```
