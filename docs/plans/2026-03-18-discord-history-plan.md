# Discord Channel History Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `discord.history(channel_id, limit=50)` that fetches channel history from the Discord API via the bridge, and update the handler to backfill `recent.log` on first access.

**Architecture:** The Discord capability writes a request to `io:discord:api:request` channel, the bridge polls it, calls `channel.history()` via discord.py, writes the response to `io:discord:api:response`. The capability polls the response channel for its request_id.

**Tech Stack:** Python, discord.py, CogOS channels (PostgreSQL), boto3 SQS

---

### Task 1: Add `history()` to Discord Capability

**Files:**
- Modify: `src/cogos/io/discord/capability.py`
- Test: `tests/cogos/test_discord_history.py`

**Step 1: Write the test**

```python
"""Tests for discord.history() capability method."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.discord.capability import DiscordCapability


@pytest.fixture
def repo():
    """Mock repository."""
    r = MagicMock()
    r.get_channel_by_name = MagicMock(return_value=None)
    r.list_channel_messages = MagicMock(return_value=[])
    return r


@pytest.fixture
def cap(repo):
    pid = uuid4()
    c = DiscordCapability(repo, pid)
    return c


class TestHistory:
    def test_history_writes_request_to_channel(self, cap, repo):
        """history() should write a request to io:discord:api:request."""
        from cogos.db.models import Channel, ChannelType
        from unittest.mock import call

        req_ch = Channel(name="io:discord:api:request", channel_type=ChannelType.NAMED)
        resp_ch = Channel(name="io:discord:api:response", channel_type=ChannelType.NAMED)

        def get_ch(name):
            if name == "io:discord:api:request":
                return req_ch
            if name == "io:discord:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name = MagicMock(side_effect=get_ch)

        # Simulate response appearing after request
        response_payload = {
            "request_id": None,  # will be matched dynamically
            "status": "ok",
            "messages": [
                {"content": "hello", "author": "alice", "author_id": "123",
                 "channel_id": "789", "message_id": "111", "timestamp": "2026-03-18T12:00:00Z",
                 "is_dm": False, "is_mention": False, "attachments": [], "thread_id": None,
                 "reference_message_id": None}
            ],
            "error": None,
        }

        call_count = [0]
        def mock_list_messages(channel_id, limit=10):
            call_count[0] += 1
            if call_count[0] >= 2:
                # Capture the request_id from the written request
                written = repo.append_channel_message.call_args
                req_payload = written[0][0].payload
                response_payload["request_id"] = req_payload["request_id"]
                msg = MagicMock()
                msg.payload = response_payload
                return [msg]
            return []

        repo.list_channel_messages = MagicMock(side_effect=mock_list_messages)

        result = cap.history("789", limit=10)

        # Verify request was written
        assert repo.append_channel_message.called
        req_msg = repo.append_channel_message.call_args[0][0]
        assert req_msg.payload["method"] == "history"
        assert req_msg.payload["channel_id"] == "789"
        assert req_msg.payload["limit"] == 10

        # Verify result
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["content"] == "hello"

    def test_history_returns_error_on_timeout(self, cap, repo):
        """history() should return DiscordError on timeout."""
        from cogos.db.models import Channel, ChannelType

        req_ch = Channel(name="io:discord:api:request", channel_type=ChannelType.NAMED)
        resp_ch = Channel(name="io:discord:api:response", channel_type=ChannelType.NAMED)

        def get_ch(name):
            if name == "io:discord:api:request":
                return req_ch
            if name == "io:discord:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name = MagicMock(side_effect=get_ch)
        repo.list_channel_messages = MagicMock(return_value=[])

        # Should timeout quickly in test
        result = cap.history("789", limit=10, _timeout=0.1, _poll_interval=0.05)
        assert hasattr(result, "error")
        assert "timeout" in result.error.lower()

    def test_history_checks_scope(self, cap, repo):
        """history() should respect capability scoping."""
        cap._scope = {"ops": {"send"}}  # no "history" op
        result = cap.history("789")
        assert hasattr(result, "error") or isinstance(result, Exception)
```

Create file: `tests/cogos/test_discord_history.py`

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/test_discord_history.py -v`
Expected: FAIL (history method doesn't exist)

**Step 3: Implement `history()` method**

Add to `src/cogos/io/discord/capability.py` in the `DiscordCapability` class, after `list_channels()`:

```python
    def history(
        self,
        channel_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
        *,
        _timeout: float = 15.0,
        _poll_interval: float = 0.5,
    ) -> list[dict] | DiscordError:
        """Fetch channel message history from the Discord API.

        Writes a request to io:discord:api:request, polls io:discord:api:response
        for the result. Returns list of message dicts or DiscordError on timeout.
        """
        self._check("history", channel=channel_id)

        request_id = str(uuid4())
        request_payload = {
            "request_id": request_id,
            "method": "history",
            "channel_id": channel_id,
            "limit": limit,
            "before": before,
            "after": after,
        }

        # Write request
        req_ch = self.repo.get_channel_by_name("io:discord:api:request")
        if req_ch is None:
            return DiscordError(error="io:discord:api:request channel not found")

        from cogos.db.models import ChannelMessage
        self.repo.append_channel_message(ChannelMessage(
            channel=req_ch.id,
            sender_process=self.process_id,
            payload=request_payload,
        ))

        # Poll for response
        resp_ch = self.repo.get_channel_by_name("io:discord:api:response")
        if resp_ch is None:
            return DiscordError(error="io:discord:api:response channel not found")

        deadline = time.time() + _timeout
        while time.time() < deadline:
            messages = self.repo.list_channel_messages(resp_ch.id, limit=20)
            for msg in messages:
                payload = msg.payload or {}
                if payload.get("request_id") == request_id:
                    if payload.get("status") == "ok":
                        return payload.get("messages", [])
                    else:
                        return DiscordError(error=payload.get("error", "unknown error"))
            time.sleep(_poll_interval)

        return DiscordError(error="Timeout waiting for Discord API response")
```

Also add `"history"` to `ALL_OPS`:

```python
ALL_OPS = {"send", "react", "create_thread", "dm", "receive", "list_channels", "list_guilds", "history"}
```

**Step 4: Run tests**

Run: `python -m pytest tests/cogos/test_discord_history.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/io/discord/capability.py tests/cogos/test_discord_history.py
git commit -m "feat(discord): add history() method to Discord capability"
```

---

### Task 2: Add API Request Polling to Bridge

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`

**Step 1: Add `_poll_api_requests()` method**

Add to the `DiscordBridge` class, after `_poll_replies()`:

```python
    async def _poll_api_requests(self):
        """Poll io:discord:api:request for API requests and respond."""
        logger.info("Starting Discord API request poller")
        loop = asyncio.get_event_loop()

        # Track processed request IDs to avoid re-processing
        seen_requests: set[str] = set()

        while True:
            try:
                repo = self._get_repo()
                req_ch = repo.get_channel_by_name("io:discord:api:request")
                if req_ch is None:
                    await asyncio.sleep(2)
                    continue

                messages = repo.list_channel_messages(req_ch.id, limit=20)
                for msg in messages:
                    payload = msg.payload or {}
                    request_id = payload.get("request_id")
                    if not request_id or request_id in seen_requests:
                        continue

                    seen_requests.add(request_id)
                    # Keep set bounded
                    if len(seen_requests) > 1000:
                        seen_requests = set(list(seen_requests)[-500:])

                    method = payload.get("method")
                    if method == "history":
                        await self._handle_history_request(repo, payload)
                    else:
                        self._write_api_response(repo, request_id, "error", error=f"Unknown method: {method}")

            except Exception:
                logger.exception("API request poll error")

            await asyncio.sleep(2)

    async def _handle_history_request(self, repo, request: dict):
        """Fetch channel history from Discord API and write response."""
        request_id = request["request_id"]
        channel_id = request.get("channel_id")
        limit = request.get("limit", 50)
        before = request.get("before")
        after = request.get("after")

        if not channel_id:
            self._write_api_response(repo, request_id, "error", error="channel_id required")
            return

        try:
            channel = self.client.get_channel(int(channel_id))
            if channel is None:
                channel = await self.client.fetch_channel(int(channel_id))

            kwargs = {"limit": min(limit, 100)}
            if before:
                kwargs["before"] = discord.Object(id=int(before))
            if after:
                kwargs["after"] = discord.Object(id=int(after))

            discord_messages = []
            async for msg in channel.history(**kwargs):
                discord_messages.append(_make_message_payload(
                    msg,
                    message_type="discord:history",
                    is_dm=isinstance(msg.channel, discord.DMChannel),
                    is_mention=False,
                ))

            # Reverse to get oldest-first (chronological)
            discord_messages.reverse()

            self._write_api_response(repo, request_id, "ok", messages=discord_messages)
            logger.info("History request %s: %d messages from channel %s", request_id, len(discord_messages), channel_id)

        except Exception as e:
            logger.exception("History request %s failed", request_id)
            self._write_api_response(repo, request_id, "error", error=str(e))

    def _write_api_response(self, repo, request_id: str, status: str, *, messages: list | None = None, error: str | None = None):
        """Write an API response to io:discord:api:response channel."""
        from cogos.db.models import ChannelMessage

        resp_ch = repo.get_channel_by_name("io:discord:api:response")
        if resp_ch is None:
            from cogos.db.models import Channel, ChannelType
            resp_ch = Channel(name="io:discord:api:response", channel_type=ChannelType.NAMED)
            repo.upsert_channel(resp_ch)
            resp_ch = repo.get_channel_by_name("io:discord:api:response")

        repo.append_channel_message(ChannelMessage(
            channel=resp_ch.id,
            sender_process=None,
            payload={
                "request_id": request_id,
                "status": status,
                "messages": messages or [],
                "error": error,
            },
        ))
```

**Step 2: Launch the poller in `on_ready`**

In `_setup_handlers`, add after the `_poll_replies` task:

```python
            self.client.loop.create_task(self._poll_api_requests())
```

**Step 3: Commit**

```bash
git add src/cogos/io/discord/bridge.py
git commit -m "feat(discord): add API request polling to bridge for history fetching"
```

---

### Task 3: Create API Channels in Init

**Files:**
- Modify: `images/cogent-v1/cogos/init.py`

**Step 1: Add channels to the boot channel list**

In init.py, add to the `for ch_name in [...]` list:

```python
    "io:discord:api:request",
    "io:discord:api:response",
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/init.py
git commit -m "feat(discord): create api request/response channels on boot"
```

---

### Task 4: Update Handler to Backfill from Discord API

**Files:**
- Modify: `images/cogent-v1/apps/discord/handler/main.md`

**Step 1: Update Step 1 history block**

Replace the history reading block (around line 54-57) with:

```python
    # 4. Read conversation history for context
    log_handle = data.get(f"{conv_key}/recent.log")
    log_data = log_handle.read()
    if hasattr(log_data, 'error') or not log_data.content.strip():
        # No local log — backfill from Discord API
        history_msgs = discord.history(channel_id=channel_id, limit=50)
        if isinstance(history_msgs, list) and history_msgs:
            lines = []
            for msg in history_msgs:
                lines.append(msg.get("author", "?") + ": " + msg.get("content", ""))
            history = "\n".join(lines)
            log_handle.write(history)
        else:
            history = ""
    else:
        history = log_data.content
```

**Step 2: Commit**

```bash
git add images/cogent-v1/apps/discord/handler/main.md
git commit -m "feat(discord): backfill recent.log from Discord API when empty"
```

---

### Task 5: Update Discord Include Docs

**Files:**
- Modify: `images/cogent-v1/cogos/includes/discord.md`

**Step 1: Add history section**

Add after the `receive()` section:

```markdown
## history(channel_id, limit?, before?, after?)

```python
# Fetch recent channel history from the Discord API
messages = discord.history("123456789", limit=50)
for m in messages:
    print(f"{m['author']}: {m['content']}")

# Paginate with before/after message IDs
older = discord.history("123456789", limit=50, before="last_message_id")
```

Returns `list[dict]` — content, author, author_id, channel_id, message_id, timestamp, is_dm, is_mention, attachments, thread_id.
Results ordered oldest-first. Fetches from the Discord API via the bridge (may take a few seconds).
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/includes/discord.md
git commit -m "docs(discord): add history() to discord include docs"
```

---

### Task 6: Deploy and Test End-to-End

**Step 1: Run all tests**

```bash
python -m pytest tests/cogos/test_discord_history.py tests/cogos/test_diagnostics_cog.py -v
```

**Step 2: Deploy**

```bash
cogent dr.alpha cogtainer update lambda
cogent dr.alpha cogos image boot
cogent dr.alpha cogos reboot -y
```

**Step 3: Wait for boot and verify**

Wait 90 seconds, then check that the handler backfills on first message.

**Step 4: Commit any fixes**

```bash
git add -A && git commit -m "fix: deployment adjustments for discord history"
```
