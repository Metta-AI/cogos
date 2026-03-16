# Full-Featured Discord Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the Discord integration with channel discovery, S3 blob store for attachments, inbound/outbound file handling, and markdown-aware output.

**Architecture:** Three independent tracks: (A) Channel/guild sync via bridge events + DB models + capability, (B) Blob store capability + inbound S3 upload + outbound file sharing, (C) MD→Discord conversion + smart chunking. All use existing patterns: Pydantic models, Repository + LocalRepository, Capability base class with scope/narrow/check.

**Tech Stack:** Python 3.12+, discord.py, boto3, Pydantic, pytest

---

## Track A: Channel/Guild Sync

### Task A1: DB models — DiscordGuild and DiscordChannel

**Files:**
- Create: `src/cogos/db/models/discord_metadata.py`
- Modify: `src/cogos/db/models/__init__.py`
- Test: `tests/cogos/db/test_discord_metadata_models.py`

**Step 1: Write the test**

Create `tests/cogos/db/test_discord_metadata_models.py`:

```python
"""Tests for DiscordGuild and DiscordChannel models."""
from datetime import datetime, timezone

from cogos.db.models.discord_metadata import DiscordGuild, DiscordChannel


def test_discord_guild_basic():
    g = DiscordGuild(guild_id="123456", cogent_name="alpha", name="My Server")
    assert g.guild_id == "123456"
    assert g.cogent_name == "alpha"
    assert g.name == "My Server"
    assert g.icon_url is None
    assert g.member_count is None


def test_discord_guild_full():
    g = DiscordGuild(
        guild_id="123456",
        cogent_name="alpha",
        name="My Server",
        icon_url="https://cdn.discord.com/icons/123/abc.png",
        member_count=42,
    )
    assert g.icon_url == "https://cdn.discord.com/icons/123/abc.png"
    assert g.member_count == 42


def test_discord_channel_basic():
    ch = DiscordChannel(
        channel_id="789",
        guild_id="123456",
        name="general",
        channel_type="text",
        position=0,
    )
    assert ch.channel_id == "789"
    assert ch.guild_id == "123456"
    assert ch.name == "general"
    assert ch.topic is None
    assert ch.category is None
    assert ch.channel_type == "text"
    assert ch.position == 0


def test_discord_channel_full():
    ch = DiscordChannel(
        channel_id="789",
        guild_id="123456",
        name="dev-talk",
        topic="Development discussion",
        category="Engineering",
        channel_type="text",
        position=3,
    )
    assert ch.topic == "Development discussion"
    assert ch.category == "Engineering"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/db/test_discord_metadata_models.py -v`
Expected: FAIL — module not found

**Step 3: Write the models**

Create `src/cogos/db/models/discord_metadata.py`:

```python
"""Discord metadata models — guild and channel info synced by the bridge."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class DiscordGuild(BaseModel):
    guild_id: str
    cogent_name: str
    name: str
    icon_url: str | None = None
    member_count: int | None = None
    synced_at: datetime | None = None


class DiscordChannel(BaseModel):
    channel_id: str
    guild_id: str
    name: str
    topic: str | None = None
    category: str | None = None
    channel_type: str  # text, voice, forum, announcement, thread, etc.
    position: int = 0
    synced_at: datetime | None = None
```

**Step 4: Add to `__init__.py`**

In `src/cogos/db/models/__init__.py`, add:

```python
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
```

And add `"DiscordChannel"` and `"DiscordGuild"` to `__all__`.

**Step 5: Run test to verify it passes**

Run: `pytest tests/cogos/db/test_discord_metadata_models.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/db/models/discord_metadata.py src/cogos/db/models/__init__.py tests/cogos/db/test_discord_metadata_models.py
git commit -m "feat(models): add DiscordGuild and DiscordChannel metadata models"
```

---

### Task A2: Repository methods for Discord metadata

**Files:**
- Modify: `src/cogos/db/repository.py`
- Modify: `src/cogos/db/local_repository.py`
- Test: `tests/cogos/db/test_discord_metadata_repo.py`

**Step 1: Write the test**

Create `tests/cogos/db/test_discord_metadata_repo.py`:

```python
"""Tests for Discord metadata repository methods."""
from cogos.db.local_repository import LocalRepository
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild


def test_upsert_and_get_guild(tmp_path):
    repo = LocalRepository(str(tmp_path))
    guild = DiscordGuild(guild_id="123", cogent_name="alpha", name="Test Server")
    repo.upsert_discord_guild(guild)

    result = repo.get_discord_guild("123")
    assert result is not None
    assert result.name == "Test Server"


def test_upsert_guild_updates(tmp_path):
    repo = LocalRepository(str(tmp_path))
    guild = DiscordGuild(guild_id="123", cogent_name="alpha", name="Old Name")
    repo.upsert_discord_guild(guild)

    guild2 = DiscordGuild(guild_id="123", cogent_name="alpha", name="New Name")
    repo.upsert_discord_guild(guild2)

    result = repo.get_discord_guild("123")
    assert result.name == "New Name"


def test_list_discord_guilds(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_guild(DiscordGuild(guild_id="1", cogent_name="alpha", name="A"))
    repo.upsert_discord_guild(DiscordGuild(guild_id="2", cogent_name="alpha", name="B"))

    guilds = repo.list_discord_guilds("alpha")
    assert len(guilds) == 2


def test_upsert_and_get_discord_channel(tmp_path):
    repo = LocalRepository(str(tmp_path))
    ch = DiscordChannel(channel_id="789", guild_id="123", name="general", channel_type="text")
    repo.upsert_discord_channel(ch)

    result = repo.get_discord_channel("789")
    assert result is not None
    assert result.name == "general"


def test_list_discord_channels(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="general", channel_type="text"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="2", guild_id="123", name="random", channel_type="text"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="3", guild_id="456", name="other", channel_type="text"))

    channels = repo.list_discord_channels(guild_id="123")
    assert len(channels) == 2
    names = {ch.name for ch in channels}
    assert names == {"general", "random"}


def test_list_discord_channels_all(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="a", channel_type="text"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="2", guild_id="456", name="b", channel_type="text"))

    channels = repo.list_discord_channels()
    assert len(channels) == 2


def test_delete_discord_channel(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="general", channel_type="text"))
    repo.delete_discord_channel("1")
    assert repo.get_discord_channel("1") is None


def test_delete_discord_guild_cascades(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_guild(DiscordGuild(guild_id="123", cogent_name="alpha", name="Server"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="general", channel_type="text"))

    repo.delete_discord_guild("123")
    assert repo.get_discord_guild("123") is None
    assert repo.get_discord_channel("1") is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/db/test_discord_metadata_repo.py -v`
Expected: FAIL — methods don't exist

**Step 3: Implement LocalRepository methods**

Add to `LocalRepository.__init__`:
```python
self._discord_guilds: dict[str, DiscordGuild] = {}
self._discord_channels: dict[str, DiscordChannel] = {}
```

Add to imports and `_reset_state`, `_serialize_state`, `_load` (follow the existing pattern for channels/processes).

Add methods:
```python
def upsert_discord_guild(self, guild: DiscordGuild) -> None:
    from datetime import datetime, timezone
    guild.synced_at = datetime.now(timezone.utc)
    self._discord_guilds[guild.guild_id] = guild
    self._save()

def get_discord_guild(self, guild_id: str) -> DiscordGuild | None:
    return self._discord_guilds.get(guild_id)

def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]:
    guilds = list(self._discord_guilds.values())
    if cogent_name:
        guilds = [g for g in guilds if g.cogent_name == cogent_name]
    return guilds

def delete_discord_guild(self, guild_id: str) -> None:
    self._discord_guilds.pop(guild_id, None)
    self._discord_channels = {
        k: v for k, v in self._discord_channels.items() if v.guild_id != guild_id
    }
    self._save()

def upsert_discord_channel(self, channel: DiscordChannel) -> None:
    from datetime import datetime, timezone
    channel.synced_at = datetime.now(timezone.utc)
    self._discord_channels[channel.channel_id] = channel
    self._save()

def get_discord_channel(self, channel_id: str) -> DiscordChannel | None:
    return self._discord_channels.get(channel_id)

def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]:
    channels = list(self._discord_channels.values())
    if guild_id:
        channels = [ch for ch in channels if ch.guild_id == guild_id]
    return sorted(channels, key=lambda ch: ch.position)

def delete_discord_channel(self, channel_id: str) -> None:
    self._discord_channels.pop(channel_id, None)
    self._save()
```

Also add serialization/deserialization in `_serialize_state` and `_load` following the existing pattern.

**Step 4: Add stub methods to Repository (RDS)**

Add matching methods to `src/cogos/db/repository.py` with SQL:
- `upsert_discord_guild` — `INSERT ... ON CONFLICT (guild_id) DO UPDATE`
- `get_discord_guild` — `SELECT * FROM cogos_discord_guild WHERE guild_id = :id`
- `list_discord_guilds` — `SELECT * FROM cogos_discord_guild WHERE cogent_name = :name`
- `delete_discord_guild` — `DELETE FROM cogos_discord_guild WHERE guild_id = :id` + cascade channels
- Same pattern for channels

Add the DB schema creation SQL to the migration/init (find where `CREATE TABLE cogos_channel` is and add the new tables nearby):

```sql
CREATE TABLE IF NOT EXISTS cogos_discord_guild (
    guild_id TEXT PRIMARY KEY,
    cogent_name TEXT NOT NULL,
    name TEXT NOT NULL,
    icon_url TEXT,
    member_count INTEGER,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cogos_discord_channel (
    channel_id TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL REFERENCES cogos_discord_guild(guild_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    topic TEXT,
    category TEXT,
    channel_type TEXT NOT NULL,
    position INTEGER DEFAULT 0,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/cogos/db/test_discord_metadata_repo.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/db/local_repository.py src/cogos/db/repository.py tests/cogos/db/test_discord_metadata_repo.py
git commit -m "feat(db): add Discord guild/channel metadata repository methods"
```

---

### Task A3: Bridge guild/channel sync on startup + events

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`
- Test: `tests/io/test_discord_bridge_sync.py`

**Step 1: Write the test**

Create `tests/io/test_discord_bridge_sync.py`:

```python
"""Tests for Discord bridge guild/channel sync."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import discord
import pytest

from cogos.io.discord.bridge import DiscordBridge


def _make_bridge():
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "test-bot"
    bridge.bot_token = "fake-token"
    bridge.reply_queue_url = ""
    bridge.region = "us-east-1"
    bridge._sqs_client = MagicMock()
    bridge._typing_tasks = {}
    bridge._repo = None
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999
    bridge.client.user.mentioned_in = MagicMock(return_value=False)
    return bridge


def _make_guild(*, guild_id=100, name="Test Server", member_count=10, channels=None):
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.name = name
    guild.icon = MagicMock()
    guild.icon.url = "https://cdn.discord.com/icons/100/abc.png"
    guild.member_count = member_count
    guild.channels = channels or []
    return guild


def _make_text_channel(*, channel_id=200, name="general", topic=None, category_name=None, position=0):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    ch.name = name
    ch.topic = topic
    ch.position = position
    ch.type = discord.ChannelType.text
    if category_name:
        cat = MagicMock()
        cat.name = category_name
        ch.category = cat
    else:
        ch.category = None
    return ch


class TestGuildSync:
    async def test_sync_guilds_writes_to_repo(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        ch1 = _make_text_channel(channel_id=201, name="general", topic="Chat here")
        ch2 = _make_text_channel(channel_id=202, name="dev", category_name="Engineering")
        guild = _make_guild(guild_id=100, name="My Server", channels=[ch1, ch2])

        await bridge._sync_guild(guild)

        repo.upsert_discord_guild.assert_called_once()
        g = repo.upsert_discord_guild.call_args.args[0]
        assert g.guild_id == "100"
        assert g.name == "My Server"

        assert repo.upsert_discord_channel.call_count == 2

    async def test_sync_guild_skips_voice_channels(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        text_ch = _make_text_channel(channel_id=201, name="general")
        voice_ch = MagicMock(spec=discord.VoiceChannel)
        voice_ch.id = 202
        voice_ch.name = "Voice"
        voice_ch.type = discord.ChannelType.voice
        voice_ch.topic = None
        voice_ch.position = 1
        voice_ch.category = None
        guild = _make_guild(channels=[text_ch, voice_ch])

        await bridge._sync_guild(guild)

        # Both channels should be synced (voice too — we store metadata for all)
        assert repo.upsert_discord_channel.call_count == 2

    async def test_on_channel_delete_removes_from_repo(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        ch = _make_text_channel(channel_id=201, name="deleted")
        bridge._on_channel_delete(ch)

        repo.delete_discord_channel.assert_called_once_with("201")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_discord_bridge_sync.py -v`
Expected: FAIL — `_sync_guild` and `_on_channel_delete` don't exist

**Step 3: Implement sync methods**

Add to `DiscordBridge`:

```python
async def _sync_guild(self, guild: discord.Guild) -> None:
    """Sync a guild and its channels to the DB."""
    from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild

    repo = self._get_repo()
    repo.upsert_discord_guild(DiscordGuild(
        guild_id=str(guild.id),
        cogent_name=self.cogent_name,
        name=guild.name,
        icon_url=guild.icon.url if guild.icon else None,
        member_count=guild.member_count,
    ))

    for ch in guild.channels:
        repo.upsert_discord_channel(DiscordChannel(
            channel_id=str(ch.id),
            guild_id=str(guild.id),
            name=ch.name,
            topic=getattr(ch, "topic", None),
            category=ch.category.name if ch.category else None,
            channel_type=ch.type.name,
            position=ch.position,
        ))
    logger.info("Synced guild %s: %d channels", guild.name, len(guild.channels))

def _on_channel_delete(self, channel) -> None:
    """Remove a channel from the DB."""
    repo = self._get_repo()
    repo.delete_discord_channel(str(channel.id))
    logger.info("Removed channel %s (%s)", channel.name, channel.id)
```

Update `_setup_handlers` to add event hooks:

```python
@self.client.event
async def on_ready():
    logger.info("Discord bridge connected as %s", self.client.user)
    # Sync all guilds/channels
    for guild in self.client.guilds:
        await self._sync_guild(guild)
    self.client.loop.create_task(self._poll_replies())

@self.client.event
async def on_guild_channel_create(channel):
    await self._sync_guild(channel.guild)

@self.client.event
async def on_guild_channel_update(before, after):
    await self._sync_guild(after.guild)

@self.client.event
async def on_guild_channel_delete(channel):
    self._on_channel_delete(channel)

@self.client.event
async def on_guild_join(guild):
    await self._sync_guild(guild)

@self.client.event
async def on_guild_remove(guild):
    repo = self._get_repo()
    repo.delete_discord_guild(str(guild.id))
```

Also add `intents.guilds = True` to the `__init__` intents setup.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/io/test_discord_bridge_sync.py -v`
Expected: PASS

**Step 5: Run existing bridge tests for regression**

Run: `pytest tests/io/test_discord_bridge.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/io/discord/bridge.py tests/io/test_discord_bridge_sync.py
git commit -m "feat(bridge): sync Discord guilds/channels to DB on startup and events"
```

---

### Task A4: Capability — list_channels() and list_guilds()

**Files:**
- Modify: `src/cogos/io/discord/capability.py`
- Modify: `src/cogos/capabilities/__init__.py` (update schema)
- Test: `tests/cogos/io/test_discord_list_channels.py`

**Step 1: Write the test**

Create `tests/cogos/io/test_discord_list_channels.py`:

```python
"""Tests for DiscordCapability list_channels/list_guilds."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
from cogos.io.discord.capability import DiscordCapability


def _make_cap(repo=None):
    repo = repo or MagicMock()
    return DiscordCapability(repo, uuid4())


def test_list_guilds():
    repo = MagicMock()
    repo.list_discord_guilds.return_value = [
        DiscordGuild(guild_id="1", cogent_name="alpha", name="Server A"),
        DiscordGuild(guild_id="2", cogent_name="alpha", name="Server B"),
    ]
    cap = _make_cap(repo)
    guilds = cap.list_guilds()
    assert len(guilds) == 2
    assert guilds[0].guild_id == "1"


def test_list_channels():
    repo = MagicMock()
    repo.list_discord_channels.return_value = [
        DiscordChannel(channel_id="10", guild_id="1", name="general", channel_type="text"),
        DiscordChannel(channel_id="11", guild_id="1", name="random", channel_type="text"),
    ]
    cap = _make_cap(repo)
    channels = cap.list_channels(guild_id="1")
    assert len(channels) == 2
    repo.list_discord_channels.assert_called_once_with(guild_id="1")


def test_list_channels_scoped():
    """Scoped capability only returns channels in allowed list."""
    repo = MagicMock()
    repo.list_discord_channels.return_value = [
        DiscordChannel(channel_id="10", guild_id="1", name="general", channel_type="text"),
        DiscordChannel(channel_id="11", guild_id="1", name="secret", channel_type="text"),
    ]
    cap = _make_cap(repo)
    scoped = cap.scope(channels=["10"])
    channels = scoped.list_channels()
    assert len(channels) == 1
    assert channels[0].channel_id == "10"


def test_list_channels_no_scope_returns_all():
    repo = MagicMock()
    repo.list_discord_channels.return_value = [
        DiscordChannel(channel_id="10", guild_id="1", name="general", channel_type="text"),
    ]
    cap = _make_cap(repo)
    channels = cap.list_channels()
    assert len(channels) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/io/test_discord_list_channels.py -v`
Expected: FAIL — methods don't exist

**Step 3: Implement**

Add to `DiscordCapability` in `src/cogos/io/discord/capability.py`:

```python
from cogos.db.models.discord_metadata import DiscordChannel as DiscordChannelInfo, DiscordGuild as DiscordGuildInfo

def list_guilds(self) -> list[DiscordGuildInfo]:
    """List guilds the bot is connected to."""
    self._check("list_guilds")
    return self.repo.list_discord_guilds()

def list_channels(self, guild_id: str | None = None) -> list[DiscordChannelInfo]:
    """List available Discord channels. Optionally filter by guild."""
    self._check("list_channels")
    channels = self.repo.list_discord_channels(guild_id=guild_id)

    # Apply scope filtering
    allowed = self._scope.get("channels")
    if allowed is not None:
        channels = [ch for ch in channels if ch.channel_id in allowed]

    return channels
```

Update `ALL_OPS` to include the new ops:
```python
ALL_OPS = {"send", "react", "create_thread", "dm", "receive", "list_channels", "list_guilds"}
```

Update the schema in `src/cogos/capabilities/__init__.py` for the discord entry — add `list_channels` and `list_guilds` ops to the scope enum and add schema entries.

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/io/test_discord_list_channels.py -v`
Expected: PASS

**Step 5: Run existing discord capability tests**

Run: `pytest tests/cogos/io/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/io/discord/capability.py src/cogos/capabilities/__init__.py tests/cogos/io/test_discord_list_channels.py
git commit -m "feat(discord): add list_channels() and list_guilds() to DiscordCapability"
```

---

### Task A5: Update discord.md include with new API docs

**Files:**
- Modify: `images/cogent-v1/cogos/includes/discord.md`

**Step 1: Add docs for new methods**

Append to the existing discord.md:

```markdown
## list_guilds()

```python
guilds = discord.list_guilds()
for g in guilds:
    print(f"{g.name} ({g.guild_id}) — {g.member_count} members")
```

Returns `list[DiscordGuildInfo]` — guild_id, name, icon_url, member_count.

## list_channels(guild_id?)

```python
# All channels across all guilds
channels = discord.list_channels()

# Channels in a specific guild
channels = discord.list_channels(guild_id="123456")

for ch in channels:
    print(f"#{ch.name} ({ch.channel_id}) — {ch.channel_type}, topic: {ch.topic}")
```

Returns `list[DiscordChannelInfo]` — channel_id, guild_id, name, topic, category, channel_type, position.
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/includes/discord.md
git commit -m "docs: add list_channels/list_guilds to discord include"
```

---

## Track B: Blob Store + Attachments

### Task B1: BlobCapability — upload and download via S3

**Files:**
- Create: `src/cogos/capabilities/blob.py`
- Modify: `src/cogos/capabilities/__init__.py`
- Test: `tests/cogos/capabilities/test_blob.py`

**Step 1: Write the test**

Create `tests/cogos/capabilities/test_blob.py`:

```python
"""Tests for BlobCapability."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.blob import BlobCapability, BlobRef, BlobContent, BlobError


def _make_cap(bucket="test-bucket"):
    repo = MagicMock()
    cap = BlobCapability(repo, uuid4())
    cap._bucket = bucket
    cap._s3_client = MagicMock()
    return cap


def test_upload_returns_blob_ref():
    cap = _make_cap()
    cap._s3_client.generate_presigned_url.return_value = "https://s3.../presigned"

    result = cap.upload(b"hello world", "test.txt", content_type="text/plain")

    assert isinstance(result, BlobRef)
    assert result.filename == "test.txt"
    assert result.size == 11
    assert result.url == "https://s3.../presigned"
    assert result.key.startswith("blobs/")
    assert result.key.endswith("/test.txt")

    cap._s3_client.put_object.assert_called_once()
    call_kwargs = cap._s3_client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "test-bucket"
    assert call_kwargs["Body"] == b"hello world"
    assert call_kwargs["ContentType"] == "text/plain"


def test_upload_empty_data():
    cap = _make_cap()
    result = cap.upload(b"", "empty.txt")
    assert isinstance(result, BlobError)
    assert "empty" in result.error.lower()


def test_download_returns_content():
    cap = _make_cap()
    body_mock = MagicMock()
    body_mock.read.return_value = b"file data"
    cap._s3_client.get_object.return_value = {
        "Body": body_mock,
        "ContentType": "text/plain",
    }

    result = cap.download("blobs/abc/test.txt")

    assert isinstance(result, BlobContent)
    assert result.data == b"file data"
    assert result.filename == "test.txt"
    assert result.content_type == "text/plain"


def test_download_invalid_key():
    cap = _make_cap()
    result = cap.download("")
    assert isinstance(result, BlobError)


def test_upload_scope_max_size():
    cap = _make_cap()
    scoped = cap.scope(max_size_bytes=10)
    result = scoped.upload(b"x" * 100, "big.bin")
    assert isinstance(result, BlobError)
    assert "size" in result.error.lower()


def test_upload_scope_ops_blocked():
    cap = _make_cap()
    scoped = cap.scope(ops=["download"])
    result = scoped.upload(b"data", "test.txt")
    assert isinstance(result, BlobError)


def test_download_scope_ops_blocked():
    cap = _make_cap()
    scoped = cap.scope(ops=["upload"])
    result = scoped.download("blobs/abc/test.txt")
    assert isinstance(result, BlobError)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_blob.py -v`
Expected: FAIL — module not found

**Step 3: Implement BlobCapability**

Create `src/cogos/capabilities/blob.py`:

```python
"""Blob store capability — upload/download files via S3 for cross-capability sharing."""
from __future__ import annotations

import logging
import os
from uuid import uuid4

import boto3
from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

PRESIGNED_URL_EXPIRY = 7 * 24 * 3600  # 7 days


class BlobRef(BaseModel):
    key: str
    url: str
    filename: str
    size: int


class BlobContent(BaseModel):
    data: bytes
    filename: str
    content_type: str | None

    class Config:
        arbitrary_types_allowed = True


class BlobError(BaseModel):
    error: str


class BlobCapability(Capability):
    """Upload and download files via S3 for cross-capability sharing.

    Usage:
        ref = blob.upload(data, "chart.png", content_type="image/png")
        content = blob.download(ref.key)
    """

    ALL_OPS = {"upload", "download"}

    def __init__(self, repo, process_id, run_id=None):
        super().__init__(repo, process_id, run_id)
        self._bucket = os.environ.get("SESSIONS_BUCKET", "")
        self._s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}

        e_ops = existing.get("ops")
        r_ops = requested.get("ops")
        if e_ops is not None and r_ops is not None:
            result["ops"] = set(e_ops) & set(r_ops)
        elif e_ops is not None:
            result["ops"] = e_ops
        elif r_ops is not None:
            result["ops"] = r_ops

        e_max = existing.get("max_size_bytes")
        r_max = requested.get("max_size_bytes")
        if e_max is not None and r_max is not None:
            result["max_size_bytes"] = min(e_max, r_max)
        elif e_max is not None:
            result["max_size_bytes"] = e_max
        elif r_max is not None:
            result["max_size_bytes"] = r_max

        return result

    def _check_op(self, op: str) -> str | None:
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            return f"Operation '{op}' not allowed by scope"
        return None

    def upload(self, data: bytes, filename: str, content_type: str | None = None) -> BlobRef | BlobError:
        """Upload bytes to the blob store. Returns a BlobRef with key and presigned URL."""
        err = self._check_op("upload")
        if err:
            return BlobError(error=err)

        if not data:
            return BlobError(error="Cannot upload empty data")

        max_size = self._scope.get("max_size_bytes")
        if max_size is not None and len(data) > max_size:
            return BlobError(error=f"Data size {len(data)} exceeds max size {max_size}")

        key = f"blobs/{uuid4()}/{filename}"

        put_kwargs: dict = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            put_kwargs["ContentType"] = content_type

        try:
            self._s3_client.put_object(**put_kwargs)
            url = self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=PRESIGNED_URL_EXPIRY,
            )
            return BlobRef(key=key, url=url, filename=filename, size=len(data))
        except Exception as e:
            return BlobError(error=str(e))

    def download(self, key: str) -> BlobContent | BlobError:
        """Download a blob by key."""
        err = self._check_op("download")
        if err:
            return BlobError(error=err)

        if not key:
            return BlobError(error="Key is required")

        try:
            resp = self._s3_client.get_object(Bucket=self._bucket, Key=key)
            data = resp["Body"].read()
            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            return BlobContent(
                data=data,
                filename=filename,
                content_type=resp.get("ContentType"),
            )
        except Exception as e:
            return BlobError(error=str(e))

    def __repr__(self) -> str:
        return "<BlobCapability upload() download()>"
```

**Step 4: Register in `__init__.py`**

Add to `BUILTIN_CAPABILITIES` in `src/cogos/capabilities/__init__.py`:

```python
{
    "name": "blob",
    "description": "Upload and download files via S3 for cross-capability sharing.",
    "handler": "cogos.capabilities.blob.BlobCapability",
    "instructions": (
        "Use blob to share files between capabilities (discord, email, etc.).\n"
        "- ref = blob.upload(data, filename, content_type?) — upload bytes, get BlobRef with key and URL\n"
        "- content = blob.download(key) — download by key, get BlobContent with data\n"
        "BlobRef.key is the durable identifier. BlobRef.url is a presigned URL (7 day expiry).\n"
        "Blobs are stored in S3 and auto-deleted after 30 days."
    ),
    "schema": {
        "scope": {
            "properties": {
                "ops": {"type": "array", "items": {"type": "string", "enum": ["upload", "download"]}},
                "max_size_bytes": {"type": "integer", "description": "Maximum upload size in bytes"},
            },
        },
        "upload": {
            "input": {
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "Raw bytes to upload"},
                    "filename": {"type": "string", "description": "Filename for the blob"},
                    "content_type": {"type": "string", "description": "MIME type"},
                },
                "required": ["data", "filename"],
            },
            "output": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"}, "url": {"type": "string"},
                    "filename": {"type": "string"}, "size": {"type": "integer"},
                },
            },
        },
        "download": {
            "input": {
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Blob key from upload"}},
                "required": ["key"],
            },
            "output": {
                "type": "object",
                "properties": {
                    "data": {"type": "string"}, "filename": {"type": "string"},
                    "content_type": {"type": "string"},
                },
            },
        },
    },
},
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_blob.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/blob.py src/cogos/capabilities/__init__.py tests/cogos/capabilities/test_blob.py
git commit -m "feat(capabilities): add BlobCapability for S3 file sharing"
```

---

### Task B2: Bridge inbound attachment pipeline — download to S3

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`
- Test: `tests/io/test_discord_bridge_attachments.py`

**Step 1: Write the test**

Create `tests/io/test_discord_bridge_attachments.py`:

```python
"""Tests for inbound attachment S3 upload in Discord bridge."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
import pytest

from cogos.io.discord.bridge import DiscordBridge


def _make_bridge_with_s3():
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "test-bot"
    bridge.bot_token = "fake-token"
    bridge.reply_queue_url = ""
    bridge.region = "us-east-1"
    bridge._sqs_client = MagicMock()
    bridge._typing_tasks = {}
    bridge._repo = None
    bridge._s3_client = MagicMock()
    bridge._blob_bucket = "test-bucket"
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999
    bridge.client.user.mentioned_in = MagicMock(return_value=False)
    bridge._s3_client.generate_presigned_url.return_value = "https://s3.../presigned"
    return bridge


class TestInboundAttachments:
    async def test_upload_image_to_s3(self):
        bridge = _make_bridge_with_s3()

        attachment = MagicMock()
        attachment.url = "https://cdn.discord.com/img.png"
        attachment.filename = "img.png"
        attachment.content_type = "image/png"
        attachment.size = 1024
        attachment.width = 800
        attachment.height = 600

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.read = AsyncMock(return_value=b"image data")
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await bridge._upload_attachment_to_s3(attachment)

        assert result is not None
        assert "s3_key" in result
        assert result["s3_key"].startswith("blobs/")
        assert result["s3_key"].endswith("/img.png")
        assert "s3_url" in result
        bridge._s3_client.put_object.assert_called_once()

    async def test_skip_large_attachment(self):
        bridge = _make_bridge_with_s3()

        attachment = MagicMock()
        attachment.url = "https://cdn.discord.com/big.zip"
        attachment.filename = "big.zip"
        attachment.content_type = "application/zip"
        attachment.size = 30_000_000  # > 25MB

        result = await bridge._upload_attachment_to_s3(attachment)
        assert result is None
        bridge._s3_client.put_object.assert_not_called()

    async def test_attachment_download_failure_returns_none(self):
        bridge = _make_bridge_with_s3()

        attachment = MagicMock()
        attachment.url = "https://cdn.discord.com/gone.png"
        attachment.filename = "gone.png"
        attachment.content_type = "image/png"
        attachment.size = 100

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = AsyncMock()
            mock_resp.status = 404
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await bridge._upload_attachment_to_s3(attachment)

        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_discord_bridge_attachments.py -v`
Expected: FAIL — `_upload_attachment_to_s3` doesn't exist

**Step 3: Implement**

Add S3 client initialization to `DiscordBridge.__init__`:

```python
self._blob_bucket = os.environ.get("SESSIONS_BUCKET", "")
self._s3_client = boto3.client("s3", region_name=self.region) if self._blob_bucket else None
```

Add method:

```python
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25MB

async def _upload_attachment_to_s3(self, attachment) -> dict | None:
    """Download a Discord attachment and upload to S3. Returns s3_key/s3_url or None."""
    if not self._s3_client or not self._blob_bucket:
        return None
    if attachment.size and attachment.size > self.MAX_ATTACHMENT_SIZE:
        logger.warning("Skipping oversized attachment %s (%d bytes)", attachment.filename, attachment.size)
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    logger.warning("Failed to download attachment %s: HTTP %s", attachment.filename, resp.status)
                    return None
                data = await resp.read()
    except Exception:
        logger.exception("Failed to download attachment %s", attachment.filename)
        return None

    from uuid import uuid4
    s3_key = f"blobs/{uuid4()}/{attachment.filename}"

    try:
        put_kwargs: dict = {"Bucket": self._blob_bucket, "Key": s3_key, "Body": data}
        if attachment.content_type:
            put_kwargs["ContentType"] = attachment.content_type
        self._s3_client.put_object(**put_kwargs)

        s3_url = self._s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._blob_bucket, "Key": s3_key},
            ExpiresIn=7 * 24 * 3600,
        )
        return {"s3_key": s3_key, "s3_url": s3_url}
    except Exception:
        logger.exception("Failed to upload attachment %s to S3", attachment.filename)
        return None
```

Update `_make_message_payload` to be called after S3 uploads, or update `_relay_to_db` to enrich attachment payloads after the payload is built:

```python
# In _relay_to_db, after building payload:
if self._s3_client and payload.get("attachments"):
    for att_payload, att_obj in zip(payload["attachments"], message.attachments):
        s3_result = await self._upload_attachment_to_s3(att_obj)
        if s3_result:
            att_payload["s3_key"] = s3_result["s3_key"]
            att_payload["s3_url"] = s3_result["s3_url"]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_discord_bridge_attachments.py -v`
Expected: PASS

**Step 5: Run existing bridge tests**

Run: `pytest tests/io/test_discord_bridge.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/io/discord/bridge.py tests/io/test_discord_bridge_attachments.py
git commit -m "feat(bridge): upload inbound Discord attachments to S3 blob store"
```

---

### Task B3: CDK — grant bridge S3 access to SESSIONS_BUCKET

**Files:**
- Modify: `src/cogtainer/cdk/stack.py`

**Step 1: Add SESSIONS_BUCKET env var to bridge container**

In `_create_discord_service`, add to the `environment` dict:

```python
"SESSIONS_BUCKET": self.storage.bucket.bucket_name,
```

**Step 2: Grant S3 access to bridge task role**

After the existing IAM policy statements, add:

```python
# IAM: S3 blob store access for attachments
self.storage.bucket.grant_read_write(task_def.task_role, "blobs/*")
```

**Step 3: Commit**

```bash
git add src/cogtainer/cdk/stack.py
git commit -m "feat(cdk): grant Discord bridge S3 access for blob store"
```

---

### Task B4: Outbound files via blob keys in send()

**Files:**
- Modify: `src/cogos/io/discord/capability.py`
- Modify: `src/cogos/io/discord/bridge.py`
- Test: `tests/io/test_discord_bridge_outbound_files.py`

**Step 1: Write the test**

Create `tests/io/test_discord_bridge_outbound_files.py`:

```python
"""Tests for outbound file handling via S3 blob keys."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from io import BytesIO

import discord
import pytest

from cogos.io.discord.bridge import DiscordBridge


def _make_bridge_with_s3():
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "test-bot"
    bridge.bot_token = "fake-token"
    bridge.reply_queue_url = ""
    bridge.region = "us-east-1"
    bridge._sqs_client = MagicMock()
    bridge._typing_tasks = {}
    bridge._repo = None
    bridge._s3_client = MagicMock()
    bridge._blob_bucket = "test-bucket"
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999
    return bridge


class TestOutboundFiles:
    async def test_download_files_with_s3_key(self):
        bridge = _make_bridge_with_s3()
        body_mock = MagicMock()
        body_mock.read.return_value = b"file data"
        bridge._s3_client.get_object.return_value = {"Body": body_mock}

        files = await bridge._download_files([
            {"s3_key": "blobs/abc/chart.png", "filename": "chart.png"},
        ])

        assert len(files) == 1
        assert isinstance(files[0], discord.File)
        bridge._s3_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="blobs/abc/chart.png"
        )

    async def test_download_files_mixed_s3_and_url(self):
        bridge = _make_bridge_with_s3()
        body_mock = MagicMock()
        body_mock.read.return_value = b"s3 data"
        bridge._s3_client.get_object.return_value = {"Body": body_mock}

        # URL-based file will use aiohttp — mock that too
        import aiohttp
        from unittest.mock import patch

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.read = AsyncMock(return_value=b"url data")
            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)

            files = await bridge._download_files([
                {"s3_key": "blobs/abc/chart.png", "filename": "chart.png"},
                {"url": "https://example.com/f.txt", "filename": "f.txt"},
            ])

        assert len(files) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_discord_bridge_outbound_files.py -v`
Expected: FAIL — `_download_files` doesn't handle s3_key

**Step 3: Update `_download_files` in bridge**

Replace the existing `_download_files` method:

```python
async def _download_files(self, file_specs: list[dict]) -> list[discord.File]:
    if not file_specs:
        return []
    files = []

    # Collect S3 downloads
    for spec in file_specs:
        s3_key = spec.get("s3_key")
        if s3_key and self._s3_client and self._blob_bucket:
            try:
                resp = self._s3_client.get_object(Bucket=self._blob_bucket, Key=s3_key)
                data = resp["Body"].read()
                filename = spec.get("filename") or s3_key.rsplit("/", 1)[-1]
                files.append(discord.File(io.BytesIO(data), filename=filename))
            except Exception:
                logger.exception("Failed to download blob: %s", s3_key)
            continue

        # Fall back to URL download
        url = spec.get("url")
        filename = spec.get("filename", "file")
        if not url:
            continue
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.read()
                    files.append(discord.File(io.BytesIO(data), filename=filename))
        except Exception:
            logger.exception("Failed to download file: %s", url)

    return files
```

**Step 4: Update capability `send()` to accept blob keys**

In `src/cogos/io/discord/capability.py`, update `send()` to convert blob keys to the SQS format:

```python
def send(
    self,
    channel: str,
    content: str,
    *,
    thread_id: str | None = None,
    reply_to: str | None = None,
    files: list[str | dict] | None = None,
) -> SendResult | DiscordError:
    """Send a message to a Discord channel.

    files can be blob keys (str) or dicts with url/filename.
    """
    if not channel or not content:
        return DiscordError(error="'channel' and 'content' are required")
    self._check("send", channel=channel)

    body: dict = {"channel": channel, "content": content}
    if thread_id:
        body["thread_id"] = thread_id
    if reply_to:
        body["reply_to"] = reply_to
    if files:
        file_specs = []
        for f in files:
            if isinstance(f, str):
                file_specs.append({"s3_key": f, "filename": f.rsplit("/", 1)[-1]})
            else:
                file_specs.append(f)
        body["files"] = file_specs

    try:
        _send_sqs(_with_reply_meta(body, process_id=self.process_id, run_id=self.run_id))
        return SendResult(channel=channel, content_length=len(content))
    except Exception as e:
        return DiscordError(error=str(e))
```

**Step 5: Run tests**

Run: `pytest tests/io/test_discord_bridge_outbound_files.py tests/io/test_discord_bridge.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/io/discord/bridge.py src/cogos/io/discord/capability.py tests/io/test_discord_bridge_outbound_files.py
git commit -m "feat(discord): support S3 blob keys for outbound file attachments"
```

---

## Track C: Markdown-Aware Output

### Task C1: MD → Discord markdown converter

**Files:**
- Create: `src/cogos/io/discord/markdown.py`
- Test: `tests/io/test_discord_markdown.py`

**Step 1: Write the test**

Create `tests/io/test_discord_markdown.py`:

```python
"""Tests for markdown → Discord markdown conversion."""
from cogos.io.discord.markdown import convert_markdown


def test_h1_to_bold():
    assert convert_markdown("# Hello") == "**Hello**"


def test_h2_to_bold():
    assert convert_markdown("## Section") == "**Section**"


def test_h3_to_bold():
    assert convert_markdown("### Subsection") == "**Subsection**"


def test_link_to_text_url():
    assert convert_markdown("[click here](https://example.com)") == "click here (<https://example.com>)"


def test_image_to_text_url():
    assert convert_markdown("![alt text](https://example.com/img.png)") == "alt text: <https://example.com/img.png>"


def test_horizontal_rule():
    result = convert_markdown("---")
    assert "─" in result


def test_table_to_code_block():
    md = "| Name | Value |\n|------|-------|\n| foo  | bar   |"
    result = convert_markdown(md)
    assert result.startswith("```\n")
    assert result.endswith("\n```")
    assert "foo" in result


def test_passthrough_bold():
    assert convert_markdown("**bold**") == "**bold**"


def test_passthrough_italic():
    assert convert_markdown("*italic*") == "*italic*"


def test_passthrough_code_inline():
    assert convert_markdown("`code`") == "`code`"


def test_passthrough_code_block():
    md = "```python\nprint('hi')\n```"
    assert convert_markdown(md) == md


def test_passthrough_list():
    md = "- item 1\n- item 2"
    assert convert_markdown(md) == md


def test_passthrough_quote():
    md = "> quoted text"
    assert convert_markdown(md) == md


def test_mixed_content():
    md = "# Title\n\nSome **bold** text.\n\n[link](https://x.com)\n\n- item"
    result = convert_markdown(md)
    assert result.startswith("**Title**")
    assert "**bold**" in result
    assert "link (<https://x.com>)" in result
    assert "- item" in result


def test_heading_inside_code_block_not_converted():
    md = "```\n# this is a comment\n```"
    result = convert_markdown(md)
    assert "# this is a comment" in result
    assert "**this is a comment**" not in result


def test_link_inside_code_block_not_converted():
    md = "```\n[not a link](url)\n```"
    result = convert_markdown(md)
    assert "[not a link](url)" in result
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_discord_markdown.py -v`
Expected: FAIL — module not found

**Step 3: Implement**

Create `src/cogos/io/discord/markdown.py`:

```python
"""Convert standard markdown to Discord-compatible markdown."""
from __future__ import annotations

import re

# Horizontal rule replacement
_HR_LINE = "─" * 20

# Regex patterns
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HR_RE = re.compile(r"^---+\s*$", re.MULTILINE)

# Table detection: line starting with |
_TABLE_LINE_RE = re.compile(r"^\|.*\|$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def convert_markdown(content: str) -> str:
    """Convert standard markdown to Discord-flavored markdown.

    Preserves content inside code blocks (``` ... ```) unchanged.
    """
    # Split on code blocks to avoid transforming code
    parts = re.split(r"(```[^`]*```)", content, flags=re.DOTALL)

    result_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # Inside a code block — pass through
            result_parts.append(part)
        else:
            result_parts.append(_convert_prose(part))

    return "".join(result_parts)


def _convert_prose(text: str) -> str:
    """Convert non-code-block markdown text."""
    # Convert tables first (multi-line)
    text = _convert_tables(text)

    # Images before links (images have ! prefix)
    text = _IMAGE_RE.sub(r"\1: <\2>", text)

    # Links
    text = _LINK_RE.sub(r"\1 (<\2>)", text)

    # Headings
    text = _HEADING_RE.sub(r"**\2**", text)

    # Horizontal rules
    text = _HR_RE.sub(_HR_LINE, text)

    return text


def _convert_tables(text: str) -> str:
    """Wrap markdown tables in code blocks."""
    lines = text.split("\n")
    result: list[str] = []
    table_lines: list[str] = []
    in_table = False

    for line in lines:
        is_table_line = bool(_TABLE_LINE_RE.match(line.strip()))
        is_sep_line = bool(_TABLE_SEP_RE.match(line.strip()))

        if is_table_line or is_sep_line:
            if not in_table:
                in_table = True
            table_lines.append(line)
        else:
            if in_table:
                result.append("```\n" + "\n".join(table_lines) + "\n```")
                table_lines = []
                in_table = False
            result.append(line)

    if in_table:
        result.append("```\n" + "\n".join(table_lines) + "\n```")

    return "\n".join(result)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_discord_markdown.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/io/discord/markdown.py tests/io/test_discord_markdown.py
git commit -m "feat(discord): add markdown-to-Discord-flavored-markdown converter"
```

---

### Task C2: Markdown-aware chunking

**Files:**
- Modify: `src/cogos/io/discord/chunking.py`
- Modify: `tests/io/test_discord_chunking.py`

**Step 1: Write the test**

Add to `tests/io/test_discord_chunking.py`:

```python
"""Tests for markdown-aware chunking."""
from cogos.io.discord.chunking import chunk_message, DISCORD_MAX_LENGTH


def test_no_split_inside_code_block():
    """A code block that fits in one chunk should never be split."""
    code = "```python\n" + "x = 1\n" * 50 + "```"
    assert len(code) < DISCORD_MAX_LENGTH
    chunks = chunk_message(code)
    assert len(chunks) == 1
    assert chunks[0] == code


def test_code_block_at_boundary_moves_to_next_chunk():
    """If a code block would cross the boundary, start a new chunk."""
    prefix = "a" * 1900 + "\n"
    code = "```python\n" + "x = 1\n" * 10 + "```"
    content = prefix + code
    assert len(content) > DISCORD_MAX_LENGTH

    chunks = chunk_message(content)
    assert len(chunks) == 2
    # Code block should be intact in second chunk
    assert "```python" in chunks[1]
    assert chunks[1].rstrip().endswith("```")


def test_oversized_code_block_split_with_fence():
    """A single code block > 2000 chars should be split with close/reopen fences."""
    code = "```python\n" + "x = 1\n" * 500 + "```"
    assert len(code) > DISCORD_MAX_LENGTH

    chunks = chunk_message(code)
    assert len(chunks) >= 2
    # Each chunk should be a valid code block
    for chunk in chunks:
        assert chunk.strip().startswith("```")
        assert chunk.strip().endswith("```")


def test_prefer_blank_line_split():
    """Should prefer splitting on blank lines over arbitrary newlines."""
    block1 = "First paragraph.\n" * 40  # ~680 chars
    block2 = "Second paragraph.\n" * 40  # ~720 chars
    block3 = "Third paragraph.\n" * 40  # ~680 chars
    content = block1 + "\n" + block2 + "\n" + block3

    chunks = chunk_message(content)
    # Should split between paragraphs, not mid-paragraph
    for chunk in chunks:
        lines = chunk.strip().split("\n")
        # No chunk should start or end mid-paragraph (with content from another)
        assert len(chunk) <= DISCORD_MAX_LENGTH


def test_existing_behavior_preserved():
    """Short messages should still work."""
    assert chunk_message("hello") == ["hello"]
    assert chunk_message("") == []
    assert chunk_message("a" * 2000) == ["a" * 2000]
```

**Step 2: Run test to verify new tests fail**

Run: `pytest tests/io/test_discord_chunking.py -v`
Expected: Some new tests FAIL

**Step 3: Rewrite chunk_message**

Replace the implementation in `src/cogos/io/discord/chunking.py`:

```python
"""Split messages to fit within Discord's 2000-character limit.

Markdown-aware: preserves code blocks, prefers splitting on blank lines.
"""
from __future__ import annotations

import re

DISCORD_MAX_LENGTH = 2000

_CODE_FENCE_RE = re.compile(r"^```(\w*)", re.MULTILINE)


def chunk_message(content: str) -> list[str]:
    """Split content into chunks that fit Discord's message limit.

    Rules:
    1. Never split inside a code block if it fits in one chunk.
    2. If a code block exceeds the limit, split it with close/reopen fences.
    3. Prefer splitting on: blank lines > newlines > spaces > hard cuts.
    """
    if not content:
        return []
    if len(content) <= DISCORD_MAX_LENGTH:
        return [content]

    # Parse into segments: prose and code blocks
    segments = _split_into_segments(content)

    chunks: list[str] = []
    current = ""

    for segment in segments:
        if segment["type"] == "code" and len(segment["text"]) > DISCORD_MAX_LENGTH:
            # Flush current
            if current.strip():
                chunks.extend(_chunk_prose(current))
                current = ""
            # Split oversized code block
            chunks.extend(_split_code_block(segment["text"], segment["lang"]))
        elif len(current) + len(segment["text"]) <= DISCORD_MAX_LENGTH:
            current += segment["text"]
        else:
            # Flush current
            if current.strip():
                chunks.extend(_chunk_prose(current))
            current = segment["text"]

    if current.strip():
        chunks.extend(_chunk_prose(current))

    return chunks


def _split_into_segments(content: str) -> list[dict]:
    """Split content into alternating prose and code block segments."""
    segments: list[dict] = []
    parts = re.split(r"(```\w*\n.*?```)", content, flags=re.DOTALL)

    for part in parts:
        if part.startswith("```") and part.rstrip().endswith("```"):
            # Extract language
            first_line = part.split("\n", 1)[0]
            lang = first_line[3:].strip()
            segments.append({"type": "code", "text": part, "lang": lang})
        else:
            segments.append({"type": "prose", "text": part, "lang": ""})

    return segments


def _chunk_prose(text: str) -> list[str]:
    """Split prose text respecting the character limit."""
    if not text.strip():
        return []
    if len(text) <= DISCORD_MAX_LENGTH:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= DISCORD_MAX_LENGTH:
            chunks.append(text)
            break

        # Try blank line first
        split_at = text.rfind("\n\n", 0, DISCORD_MAX_LENGTH)
        if split_at > 0:
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
            continue

        # Try newline
        split_at = text.rfind("\n", 0, DISCORD_MAX_LENGTH)
        if split_at > 0:
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
            continue

        # Try space
        split_at = text.rfind(" ", 0, DISCORD_MAX_LENGTH)
        if split_at > 0:
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
            continue

        # Hard cut
        chunks.append(text[:DISCORD_MAX_LENGTH])
        text = text[DISCORD_MAX_LENGTH:]

    return chunks


def _split_code_block(code: str, lang: str) -> list[str]:
    """Split an oversized code block into multiple valid code blocks."""
    # Strip the outer fences
    lines = code.split("\n")
    # First line is ```lang, last line is ```
    inner_lines = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]

    fence_open = f"```{lang}\n" if lang else "```\n"
    fence_close = "\n```"
    overhead = len(fence_open) + len(fence_close)
    max_inner = DISCORD_MAX_LENGTH - overhead

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in inner_lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_inner and current_lines:
            chunks.append(fence_open + "\n".join(current_lines) + fence_close)
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append(fence_open + "\n".join(current_lines) + fence_close)

    return chunks
```

**Step 4: Run tests**

Run: `pytest tests/io/test_discord_chunking.py -v`
Expected: PASS

**Step 5: Run existing chunking tests too**

Run: `pytest tests/ -k chunking -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/io/discord/chunking.py tests/io/test_discord_chunking.py
git commit -m "feat(discord): markdown-aware message chunking with code block preservation"
```

---

### Task C3: Wire conversion + chunking into bridge outbound

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`
- Test: `tests/io/test_discord_bridge.py` (add test)

**Step 1: Write the test**

Add to `tests/io/test_discord_bridge.py` in `TestBridgeOutbound`:

```python
async def test_handle_message_converts_markdown(self):
    bridge = _make_bridge()
    channel = AsyncMock()
    channel.id = 100

    await bridge._handle_message(
        {"content": "# Hello\n\n[link](https://example.com)"},
        channel,
    )

    args, kwargs = channel.send.call_args
    sent = args[0]
    assert "**Hello**" in sent
    assert "link (<https://example.com>)" in sent
    assert "# Hello" not in sent
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/io/test_discord_bridge.py::TestBridgeOutbound::test_handle_message_converts_markdown -v`
Expected: FAIL — no markdown conversion happening

**Step 3: Wire it in**

In `bridge.py`, import the converter:

```python
from cogos.io.discord.markdown import convert_markdown
```

In `_handle_message`, apply conversion before chunking:

```python
async def _handle_message(self, body: dict, channel):
    content = body.get("content", "")
    # Convert markdown for Discord
    if content:
        content = convert_markdown(content)
    # ... rest of method unchanged but uses converted content
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/io/test_discord_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/io/discord/bridge.py tests/io/test_discord_bridge.py
git commit -m "feat(bridge): apply markdown conversion to outbound Discord messages"
```

---

## Summary

| Task | Track | Component | Depends On |
|------|-------|-----------|------------|
| A1 | A | DB models: DiscordGuild, DiscordChannel | — |
| A2 | A | Repository methods for metadata | A1 |
| A3 | A | Bridge: guild/channel sync | A2 |
| A4 | A | Capability: list_channels(), list_guilds() | A2 |
| A5 | A | Update discord.md docs | A4 |
| B1 | B | BlobCapability: upload/download | — |
| B2 | B | Bridge: inbound attachment S3 upload | B1 |
| B3 | B | CDK: grant bridge S3 access | — |
| B4 | B | Outbound files via blob keys | B1 |
| C1 | C | MD → Discord converter | — |
| C2 | C | Markdown-aware chunking | — |
| C3 | C | Wire conversion into bridge | C1, C2 |

Tracks A, B, and C are independent. Within each track, tasks are sequential. A3 and A4 can run in parallel (both depend on A2). B3 can run anytime.
