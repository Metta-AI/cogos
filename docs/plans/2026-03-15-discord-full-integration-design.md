# Full-Featured Discord Integration Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the Discord integration from basic message relay to a fully-featured platform with channel discovery, image/file handling, and proper markdown rendering.

**Tech Stack:** Python, discord.py, boto3, Pydantic, pytest

---

## Architecture Overview

Four additions to the existing bridge + capability system:

1. **Channel/guild sync** — Bridge maintains a live mirror of Discord server structure in the DB
2. **Blob store** — New capability for uploading/downloading files via S3 (`/blobs/` prefix in the existing cogent bucket)
3. **Inbound attachment pipeline** — Bridge downloads images/files to S3 on receipt, replaces CDN URLs with durable S3 URLs
4. **Markdown-aware output** — Smart MD→Discord conversion + code-block-aware chunking

Data flow:
- **Inbound**: Discord message → bridge downloads attachments to S3 → writes enriched payload to DB
- **Outbound**: Cogent writes file to blob store → gets S3 key → passes key in `discord.send(files=[...])` → bridge downloads from S3 and attaches to Discord message
- **Metadata**: Bridge syncs channel/guild structure on connect + on change events → capability reads from DB via `list_channels()`

No changes to the SQS reply queue architecture.

---

## 1. Channel/Guild Sync

### DB Models

```
DiscordGuild:
  guild_id: str (Discord snowflake, PK)
  cogent_name: str
  name: str
  icon_url: str | None
  member_count: int | None
  synced_at: datetime

DiscordChannel:
  channel_id: str (Discord snowflake, PK)
  guild_id: str (FK)
  name: str
  topic: str | None
  category: str | None (parent category name)
  channel_type: str (text, voice, forum, announcement, thread, etc.)
  position: int
  synced_at: datetime
```

### Bridge Changes

- `on_ready`: Iterate all guilds/channels, upsert to DB
- Hook `on_guild_channel_create`, `on_guild_channel_update`, `on_guild_channel_delete` to keep DB current
- `on_guild_join` / `on_guild_remove` for guild-level changes

### Capability Additions

```python
def list_channels(self, guild_id: str | None = None) -> list[DiscordChannelInfo]:
    """List available Discord channels. Optionally filter by guild."""

def list_guilds(self) -> list[DiscordGuildInfo]:
    """List guilds the bot is connected to."""
```

Both read from DB — no Discord API calls at runtime. Scoping applies: if the capability is scoped to specific channels, `list_channels()` only returns those.

Designed for future extension — can add members, roles, permissions later without breaking the API.

---

## 2. Blob Store Capability

New capability: `BlobCapability` — minimal file sharing via the existing cogent S3 bucket.

### API

```python
class BlobCapability(Capability):
    def upload(self, data: bytes, filename: str, content_type: str | None = None) -> BlobRef:
        """Upload bytes, returns a BlobRef with key and URL."""

    def download(self, key: str) -> BlobContent:
        """Download by key, returns bytes + metadata."""

class BlobRef(BaseModel):
    key: str          # blobs/{uuid}/{filename}
    url: str          # presigned GET URL (expiry: 7 days)
    filename: str
    size: int

class BlobContent(BaseModel):
    data: bytes
    filename: str
    content_type: str | None
```

### S3 Layout

`s3://cogent-{safe_name}-bucket/blobs/{uuid}/{filename}` — each upload gets a unique prefix.

### Scoping

```python
blob = blob.scope(max_size_bytes=10_000_000)  # 10MB limit
blob = blob.scope(ops=["download"])            # read-only
```

### Lifecycle

S3 lifecycle policy deletes `/blobs/*` objects after 30 days. No DB tracking — the key in the message payload is the reference.

### Why separate from `files`?

`files` is the cogent's workspace (local filesystem equivalent). Blob store is for external sharing — different prefix, presigned URLs for cross-service access.

---

## 3. Inbound Attachment Pipeline

### Bridge Changes

When a message has attachments, the bridge downloads each one to `/blobs/` in the cogent S3 bucket before writing the payload to DB.

```python
for attachment in message.attachments:
    s3_key = f"blobs/{uuid4()}/{attachment.filename}"
    data = await download(attachment.url)
    s3_client.put_object(Bucket=cogent_bucket, Key=s3_key, Body=data)
    attachment_payload["s3_key"] = s3_key
    attachment_payload["s3_url"] = presign(s3_key)
```

### Enriched Attachment Payload

```python
{
    "url": "https://cdn.discordapp.com/...",       # original (may expire)
    "s3_key": "blobs/abc123/photo.png",            # durable
    "s3_url": "https://s3.../presigned...",         # presigned GET
    "filename": "photo.png",
    "content_type": "image/png",
    "size": 204800,
    "is_image": True,
    "width": 1024,
    "height": 768,
}
```

### Limits

Bridge skips S3 upload for attachments > 25MB. Logs a warning, keeps only the CDN URL.

No model changes needed — `attachments` is already `list[dict]`.

The cogent can use `blob.download(s3_key)` to fetch image data for vision model processing, or use the `s3_url` directly.

---

## 4. Outbound Files via Blob Store

### Updated `discord.send()` Flow

```python
ref = blob.upload(chart_bytes, "report.png", content_type="image/png")
discord.send(channel_id, "Here's the daily report:", files=[ref.key])
```

### Capability Changes

`send()` `files` parameter accepts blob keys (`list[str]`). The SQS message includes them. Bridge resolves:

```python
# Bridge _download_files:
for spec in file_specs:
    if "s3_key" in spec:
        data = s3_client.get_object(Bucket=cogent_bucket, Key=spec["s3_key"])
        files.append(discord.File(BytesIO(data), filename))
    elif "url" in spec:
        # Existing behavior
        ...
```

### IAM

Bridge Fargate task role needs `s3:GetObject` and `s3:PutObject` on `arn:aws:s3:::cogent-{name}-bucket/blobs/*`.

---

## 5. Markdown-Aware Output

### MD → Discord Conversion

New module: `src/cogos/io/discord/markdown.py`

Discord supports: `**bold**`, `*italic*`, `~~strike~~`, `` `code` ``, ` ```blocks``` `, `> quotes`, `- lists`.
Discord does NOT support: `# headings`, tables, `[links](url)`, `![images](url)`.

Transform rules:
| Standard MD | Discord Output |
|---|---|
| `# Heading` | `**Heading**` |
| `## Sub` | `**Sub**` |
| `\| table \|` | wrapped in ` ```\n...\n``` ` |
| `[text](url)` | `text (<url>)` |
| `![alt](url)` | `alt: <url>` |
| `---` | `─────────────` |
| Everything else | Pass through |

### Markdown-Aware Chunking

Update `chunk_message` to:
1. Never split inside a ` ``` ` code block — end chunk before, start new chunk with the block
2. If a single code block exceeds 2000 chars, split into multiple blocks (close/reopen fence with language tag)
3. Split priority: blank lines > heading boundaries > newlines > spaces > hard cut

`convert_markdown()` runs first, then `chunk_message()` on the result.

---

## Implementation Order

| Task | Component | Depends On |
|---|---|---|
| 1 | DB models: `DiscordGuild`, `DiscordChannel` | — |
| 2 | Bridge: guild/channel sync on startup + events | Task 1 |
| 3 | Capability: `list_channels()`, `list_guilds()` | Task 1 |
| 4 | `BlobCapability`: upload/download with S3 | — |
| 5 | Bridge: inbound attachment pipeline (download to S3) | Task 4 |
| 6 | Capability: outbound files via blob keys in `send()` | Task 4 |
| 7 | `markdown.py`: MD → Discord conversion | — |
| 8 | Markdown-aware `chunk_message` | Task 7 |
| 9 | Wire conversion + chunking into bridge `_handle_message` | Tasks 7, 8 |

Tasks 1-3, 4-6, and 7-9 are three independent tracks that can be developed in parallel.
