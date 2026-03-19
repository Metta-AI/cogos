# Shared Discord Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace per-cogent Discord bots with a single shared bot at the polis level, using webhooks for cogent personas and Discord roles for @mentions.

**Architecture:** One bridge Fargate service on cogent-polis cluster connects to Discord gateway, routes inbound messages to the correct cogent's scoped CogOS channels, and sends outbound replies via per-cogent webhooks. Cogents are discovered from the DynamoDB `cogent-status` table.

**Tech Stack:** Python, discord.py, boto3, AWS CDK, SQS, DynamoDB, Fargate

---

### Task 1: Scope capability channels by cogent name

Update `DiscordCapability` to use `io:discord:{cogent_name}:*` channel names and send replies to the shared polis queue.

**Files:**
- Modify: `src/cogos/io/discord/capability.py`

**Step 1: Update `_get_queue_url` to use polis queue**

Change the SQS queue URL resolution to target `cogent-polis-discord-replies` instead of per-cogent queues:

```python
def _get_queue_url() -> str:
    override = os.environ.get("DISCORD_REPLY_QUEUE_URL")
    if override:
        return override
    region = os.environ.get("AWS_REGION", "us-east-1")
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"https://sqs.{region}.amazonaws.com/{account_id}/cogent-polis-discord-replies"
```

**Step 2: Update `_with_reply_meta` to include `cogent_name`**

Add `cogent_name` to the `_meta` dict so the bridge knows which webhook to use:

```python
def _with_reply_meta(body: dict, *, process_id: UUID, run_id: UUID | None, trace_id: UUID | None = None, cogent_name: str = "") -> dict:
    meta = {
        "queued_at_ms": int(time.time() * 1000),
        "trace_id": str(trace_id) if trace_id else str(uuid4()),
        "process_id": str(process_id),
        "cogent_name": cogent_name,
    }
    if run_id is not None:
        meta["run_id"] = str(run_id)
    enriched = dict(body)
    enriched["_meta"] = meta
    return enriched
```

**Step 3: Update `DiscordCapability.__init__` to store cogent_name**

```python
def __init__(self, repo, process_id, **kwargs):
    super().__init__(repo, process_id, **kwargs)
    self._cogent_name = os.environ.get("COGENT_NAME", "")
    # ... rest unchanged
```

**Step 4: Update all `_send_sqs` calls to pass `cogent_name`**

In `send()`, `react()`, `create_thread()`, `dm()` — pass `cogent_name=self._cogent_name` to `_with_reply_meta`.

**Step 5: Update `receive()` to use scoped channel names**

```python
def receive(self, limit: int = 10, message_type: str | None = None) -> list[DiscordMessage]:
    self._check("receive")
    cn = self._cogent_name

    if message_type:
        channel_names = [f"io:discord:{cn}:{message_type.split(':')[1]}"]
    else:
        channel_names = [f"io:discord:{cn}:dm", f"io:discord:{cn}:mention", f"io:discord:{cn}:message"]

    # ... rest unchanged
```

**Step 6: Update `history()` to use scoped API channels**

Change `io:discord:api:request` → `io:discord:{cogent_name}:api:request` and `io:discord:api:response` → `io:discord:{cogent_name}:api:response`.

**Step 7: Verify tests still pass**

Run: `python -m pytest tests/ -k discord -v --no-header 2>&1 | head -50`

**Step 8: Commit**

```bash
git add src/cogos/io/discord/capability.py
git commit -m "feat(discord): scope capability channels by cogent name, target polis queue"
```

---

### Task 2: Add cogent registry reader for the bridge

Create a module that reads the DynamoDB `cogent-status` table to discover Discord-enabled cogents and their config (display name, avatar, color, default channels).

**Files:**
- Create: `src/cogos/io/discord/registry.py`

**Step 1: Create the registry module**

```python
"""Read cogent registry from DynamoDB for Discord bridge routing."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import boto3

logger = logging.getLogger(__name__)

DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "cogent-status")


@dataclass
class CogentDiscordConfig:
    """Discord configuration for a single cogent."""
    cogent_name: str
    display_name: str = ""
    avatar_url: str = ""
    color: int = 0  # Discord role color as int
    default_channels: list[str] = field(default_factory=list)
    db_resource_arn: str = ""
    db_secret_arn: str = ""
    db_name: str = "cogent"

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.cogent_name


def load_cogent_configs(table_name: str = DYNAMO_TABLE) -> list[CogentDiscordConfig]:
    """Scan DynamoDB cogent-status table for all cogents."""
    dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    table = dynamodb.Table(table_name)
    items = table.scan().get("Items", [])

    configs = []
    for item in items:
        name = item.get("cogent_name", "")
        if not name:
            continue
        # Extract discord config from the manifest if present
        manifest = item.get("manifest") or {}
        if isinstance(manifest, str):
            import json
            try:
                manifest = json.loads(manifest)
            except Exception:
                manifest = {}

        discord_cfg = manifest.get("discord", {})
        db_cfg = manifest.get("database", {})

        configs.append(CogentDiscordConfig(
            cogent_name=name,
            display_name=discord_cfg.get("display_name", name),
            avatar_url=discord_cfg.get("avatar_url", ""),
            color=discord_cfg.get("color", 0),
            default_channels=[str(c) for c in discord_cfg.get("default_channels", [])],
            db_resource_arn=db_cfg.get("cluster_arn", ""),
            db_secret_arn=db_cfg.get("secret_arn", ""),
            db_name=db_cfg.get("db_name", "cogent"),
        ))

    logger.info("Loaded %d cogent configs from %s", len(configs), table_name)
    return configs
```

**Step 2: Commit**

```bash
git add src/cogos/io/discord/registry.py
git commit -m "feat(discord): add cogent registry reader for shared bridge"
```

---

### Task 3: Add role and webhook lifecycle manager

Create a module that ensures Discord roles and webhooks exist for each cogent.

**Files:**
- Create: `src/cogos/io/discord/lifecycle.py`

**Step 1: Create the lifecycle module**

```python
"""Manage Discord roles and webhooks for cogent personas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord

from cogos.io.discord.registry import CogentDiscordConfig

logger = logging.getLogger(__name__)

ROLE_PREFIX = "cogent:"  # Roles named "cogent:dr.alpha" etc.


@dataclass
class CogentPersona:
    """Runtime state for a cogent's Discord persona."""
    config: CogentDiscordConfig
    role_id: int | None = None
    # channel_id -> webhook
    webhooks: dict[int, discord.Webhook] = field(default_factory=dict)


class LifecycleManager:
    """Ensure Discord roles and webhooks exist for each cogent."""

    def __init__(self):
        self._personas: dict[str, CogentPersona] = {}  # cogent_name -> persona

    @property
    def personas(self) -> dict[str, CogentPersona]:
        return self._personas

    def get_persona(self, cogent_name: str) -> CogentPersona | None:
        return self._personas.get(cogent_name)

    def role_name(self, cogent_name: str) -> str:
        return f"{ROLE_PREFIX}{cogent_name}"

    async def sync(self, guild: discord.Guild, configs: list[CogentDiscordConfig]) -> None:
        """Sync roles and webhooks for all cogents in a guild."""
        await self._sync_roles(guild, configs)
        await self._sync_webhooks(guild, configs)

    async def _sync_roles(self, guild: discord.Guild, configs: list[CogentDiscordConfig]) -> None:
        """Create/update mentionable roles for each cogent."""
        existing_roles = {r.name: r for r in guild.roles if r.name.startswith(ROLE_PREFIX)}
        desired_names = {self.role_name(c.cogent_name) for c in configs}

        # Create missing roles
        for cfg in configs:
            rname = self.role_name(cfg.cogent_name)
            if rname in existing_roles:
                role = existing_roles[rname]
                # Update color if needed
                if role.color.value != cfg.color:
                    try:
                        await role.edit(color=discord.Color(cfg.color))
                    except Exception:
                        logger.warning("Failed to update role color for %s", rname, exc_info=True)
            else:
                try:
                    role = await guild.create_role(
                        name=rname,
                        color=discord.Color(cfg.color),
                        mentionable=True,
                        reason="Cogent Discord persona",
                    )
                    logger.info("Created role %s (id=%s) in guild %s", rname, role.id, guild.name)
                except Exception:
                    logger.exception("Failed to create role %s in guild %s", rname, guild.name)
                    continue

            persona = self._personas.setdefault(cfg.cogent_name, CogentPersona(config=cfg))
            persona.role_id = role.id
            persona.config = cfg

        # Delete roles for removed cogents
        for rname, role in existing_roles.items():
            if rname not in desired_names:
                try:
                    await role.delete(reason="Cogent removed")
                    logger.info("Deleted role %s from guild %s", rname, guild.name)
                except Exception:
                    logger.warning("Failed to delete role %s", rname, exc_info=True)

    async def _sync_webhooks(self, guild: discord.Guild, configs: list[CogentDiscordConfig]) -> None:
        """Ensure webhooks exist per cogent per text channel."""
        config_by_name = {c.cogent_name: c for c in configs}

        for channel in guild.text_channels:
            try:
                existing_webhooks = await channel.webhooks()
            except discord.Forbidden:
                logger.debug("No webhook access in #%s", channel.name)
                continue
            except Exception:
                logger.debug("Failed to list webhooks in #%s", channel.name, exc_info=True)
                continue

            # Index existing cogent webhooks
            existing_by_name: dict[str, discord.Webhook] = {}
            for wh in existing_webhooks:
                if wh.name and wh.name.startswith("cogent-"):
                    existing_by_name[wh.name] = wh

            for cfg in configs:
                wh_name = f"cogent-{cfg.cogent_name}"
                persona = self._personas.setdefault(cfg.cogent_name, CogentPersona(config=cfg))

                if wh_name in existing_by_name:
                    persona.webhooks[channel.id] = existing_by_name[wh_name]
                else:
                    # Check webhook limit (15 per channel)
                    if len(existing_webhooks) >= 15:
                        logger.warning("Webhook limit reached in #%s, skipping %s", channel.name, cfg.cogent_name)
                        continue
                    try:
                        wh = await channel.create_webhook(
                            name=wh_name,
                            reason=f"Cogent persona: {cfg.display_name}",
                        )
                        persona.webhooks[channel.id] = wh
                        existing_webhooks.append(wh)  # track count
                        logger.info("Created webhook %s in #%s", wh_name, channel.name)
                    except Exception:
                        logger.warning("Failed to create webhook %s in #%s", wh_name, channel.name, exc_info=True)
```

**Step 2: Commit**

```bash
git add src/cogos/io/discord/lifecycle.py
git commit -m "feat(discord): add role and webhook lifecycle manager"
```

---

### Task 4: Add inbound message router

Create a module that determines which cogent(s) should receive an inbound Discord message.

**Files:**
- Create: `src/cogos/io/discord/router.py`

**Step 1: Create the router module**

```python
"""Route inbound Discord messages to the correct cogent(s)."""

from __future__ import annotations

import logging
import re

import discord

from cogos.io.discord.lifecycle import ROLE_PREFIX, LifecycleManager

logger = logging.getLogger(__name__)


class MessageRouter:
    """Determine which cogent(s) should handle an inbound message."""

    def __init__(self, lifecycle: LifecycleManager):
        self._lifecycle = lifecycle
        # (user_id) -> cogent_name for DM routing
        self._last_interaction: dict[int, str] = {}
        # thread_id -> cogent_name for thread ownership
        self._thread_owners: dict[int, str] = {}

    def update_last_interaction(self, user_id: int, cogent_name: str) -> None:
        self._last_interaction[user_id] = cogent_name

    def set_thread_owner(self, thread_id: int, cogent_name: str) -> None:
        self._thread_owners[thread_id] = cogent_name

    def route(self, message: discord.Message) -> list[str]:
        """Return list of cogent_names that should receive this message.

        Returns empty list if no cogent matches (message should be dropped).
        """
        if isinstance(message.channel, discord.DMChannel):
            return self._route_dm(message)
        return self._route_guild(message)

    def _route_guild(self, message: discord.Message) -> list[str]:
        # 1. Check role mentions
        mentioned = self._extract_role_mentions(message)
        if mentioned:
            # Update last interaction for all mentioned cogents
            for name in mentioned:
                self.update_last_interaction(message.author.id, name)
            return mentioned

        # 2. Check thread ownership
        if isinstance(message.channel, discord.Thread):
            owner = self._thread_owners.get(message.channel.id)
            if owner:
                return [owner]

        # 3. Check channel defaults
        channel_id = str(message.channel.id)
        for name, persona in self._lifecycle.personas.items():
            if channel_id in persona.config.default_channels:
                return [name]

        # 4. No match
        return []

    def _route_dm(self, message: discord.Message) -> list[str]:
        user_id = message.author.id

        # Check if user is trying to switch cogents
        switch_target = self._detect_switch(message.content)
        if switch_target:
            self.update_last_interaction(user_id, switch_target)
            return [switch_target]

        # Fall back to last interaction
        last = self._last_interaction.get(user_id)
        if last:
            return [last]

        # No prior interaction — return empty (bridge will prompt user)
        return []

    def _extract_role_mentions(self, message: discord.Message) -> list[str]:
        """Extract cogent names from role mentions in the message."""
        results = []
        for role in message.role_mentions:
            if role.name.startswith(ROLE_PREFIX):
                cogent_name = role.name[len(ROLE_PREFIX):]
                if cogent_name in self._lifecycle.personas:
                    results.append(cogent_name)
        return results

    def _detect_switch(self, content: str) -> str | None:
        """Detect if a DM is trying to switch to a different cogent."""
        if not content:
            return None
        lower = content.strip().lower()
        for name in self._lifecycle.personas:
            # Match "switch to X", "@X", or just the cogent name alone
            if lower == name.lower():
                return name
            if lower == f"@{name.lower()}":
                return name
            if re.match(rf"switch\s+to\s+{re.escape(name)}", lower, re.IGNORECASE):
                return name
        return None

    def available_cogents(self) -> list[str]:
        """List all registered cogent names."""
        return list(self._lifecycle.personas.keys())
```

**Step 2: Commit**

```bash
git add src/cogos/io/discord/router.py
git commit -m "feat(discord): add inbound message router"
```

---

### Task 5: Rewrite bridge.py as multi-tenant

Rewrite the bridge to use the registry, lifecycle manager, and router. It connects once, routes inbound to scoped channels per cogent, and sends outbound via webhooks.

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`

**Step 1: Rewrite the bridge class**

Replace the single-tenant `DiscordBridge` with a multi-tenant version. Key changes:

- Remove `self.cogent_name` — bridge serves all cogents
- On startup: load configs from DynamoDB, sync roles/webhooks via `LifecycleManager`
- Periodic sync every 60s to pick up new cogents
- `on_message`: use `MessageRouter.route()` to find target cogent(s), write to scoped channels `io:discord:{cogent_name}:*`
- Need a repo per cogent (each has its own DB). Cache repos keyed by cogent_name, create from `CogentDiscordConfig.db_resource_arn`.
- `_poll_replies`: poll single `cogent-polis-discord-replies` queue, read `cogent_name` from `_meta`, send via that cogent's webhook
- DM with no prior interaction: reply with list of available cogents
- `_poll_api_requests`: poll per-cogent `io:discord:{cogent_name}:api:request` channels

```python
"""Discord bridge: multi-tenant gateway for all cogents.

Runs as a polis-level Fargate service. Connects to Discord gateway once,
routes inbound messages to the correct cogent's scoped CogOS channels,
and sends outbound replies via per-cogent webhooks.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time

import aiohttp
import boto3
import discord

from cogos.io.discord.chunking import chunk_message
from cogos.io.discord.lifecycle import LifecycleManager
from cogos.io.discord.markdown import convert_markdown
from cogos.io.discord.registry import CogentDiscordConfig, load_cogent_configs
from cogos.io.discord.router import MessageRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message payload builder (unchanged from original)
# ---------------------------------------------------------------------------

def _make_message_payload(message: discord.Message, message_type: str, *, is_dm: bool, is_mention: bool) -> dict:
    # ... (keep existing implementation unchanged)
    pass


def _reply_queue_latency_ms(body: dict) -> int | None:
    # ... (keep existing implementation unchanged)
    pass


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------

class DiscordBridge:
    """Multi-tenant Discord bridge serving all cogents."""

    def __init__(self):
        self.bot_token = os.environ["DISCORD_BOT_TOKEN"]
        self.reply_queue_url = os.environ.get("DISCORD_REPLY_QUEUE_URL", "")
        self.region = os.environ.get("AWS_REGION", "us-east-1")
        self.dynamo_table = os.environ.get("DYNAMO_TABLE", "cogent-status")

        self._sqs_client = boto3.client("sqs", region_name=self.region)
        self._s3_client = boto3.client("s3", region_name=self.region)

        # Per-cogent DB repos: cogent_name -> repo
        self._repos: dict[str, object] = {}
        self._configs: dict[str, CogentDiscordConfig] = {}

        # Sessions bucket (shared)
        from cogos import get_sessions_bucket
        self._blob_bucket = get_sessions_bucket()

        # Lifecycle and routing
        self._lifecycle = LifecycleManager()
        self._router = MessageRouter(self._lifecycle)

        # Typing indicator tasks keyed by channel_id
        self._typing_tasks: dict[int, asyncio.Task] = {}

        # Pending DM tracker
        self._pending_dms: dict[str, tuple[str, str, float]] = {}
        self._alerted_dm_ids: set[str] = set()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guilds = True
        intents.reactions = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _get_repo(self, cogent_name: str):
        """Get or create a DB repo for a specific cogent."""
        if cogent_name not in self._repos:
            cfg = self._configs.get(cogent_name)
            if not cfg or not cfg.db_resource_arn:
                logger.warning("No DB config for cogent %s", cogent_name)
                return None
            from cogos.db.factory import create_repository
            self._repos[cogent_name] = create_repository(
                resource_arn=cfg.db_resource_arn,
                secret_arn=cfg.db_secret_arn,
                database=cfg.db_name,
            )
        return self._repos.get(cogent_name)

    # ... (keep _create_alert, _upload_attachment_to_s3,
    #      _start_typing, _stop_typing, _track_pending_dm,
    #      _clear_pending_dm, _sweep_pending_dms, _check_pending_dms
    #      with minor adjustments to use cogent-scoped repos)

    async def _sync_cogents(self):
        """Load cogent configs and sync roles/webhooks."""
        configs = await asyncio.get_event_loop().run_in_executor(
            None, load_cogent_configs, self.dynamo_table
        )
        self._configs = {c.cogent_name: c for c in configs}

        for guild in self.client.guilds:
            await self._lifecycle.sync(guild, configs)
        logger.info("Synced %d cogents across %d guilds", len(configs), len(self.client.guilds))

    async def _periodic_sync(self):
        """Re-sync cogent configs every 60s."""
        while True:
            await asyncio.sleep(60)
            try:
                await self._sync_cogents()
            except Exception:
                logger.exception("Periodic cogent sync failed")

    def _setup_handlers(self):
        @self.client.event
        async def on_ready():
            logger.info("Discord bridge connected as %s", self.client.user)
            await self._sync_cogents()
            # Sync guild metadata for all cogents
            for guild in self.client.guilds:
                for cogent_name in self._configs:
                    await self._sync_guild(guild, cogent_name)
            self.client.loop.create_task(self._poll_replies())
            self.client.loop.create_task(self._periodic_sync())
            self.client.loop.create_task(self._check_pending_dms())
            self.client.loop.create_task(self._poll_all_api_requests())

        @self.client.event
        async def on_guild_join(guild):
            await self._sync_cogents()

        @self.client.event
        async def on_message(message: discord.Message):
            if message.author == self.client.user or message.author.bot:
                return
            await self._relay_to_db(message)

        @self.client.event
        async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
            await self._on_raw_reaction_add(payload)

    async def _relay_to_db(self, message: discord.Message):
        """Route message to correct cogent(s) and write to their scoped channels."""
        targets = self._router.route(message)

        # Handle DMs with no target
        if not targets and isinstance(message.channel, discord.DMChannel):
            available = self._router.available_cogents()
            if available:
                names = ", ".join(f"`{n}`" for n in available)
                await message.channel.send(f"Who would you like to talk to? Available: {names}")
            return

        if not targets:
            return  # Drop unrouted guild messages

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

        if is_dm:
            message_type = "discord:dm"
        elif is_mention:
            message_type = "discord:mention"
        else:
            message_type = "discord:message"

        payload = _make_message_payload(message, message_type, is_dm=is_dm, is_mention=is_mention)

        # Upload attachments to S3 (once, shared)
        if self._s3_client and payload.get("attachments"):
            for att_payload, att_obj in zip(payload["attachments"], message.attachments):
                s3_result = await self._upload_attachment_to_s3(att_obj)
                if s3_result:
                    att_payload["s3_key"] = s3_result["s3_key"]
                    att_payload["s3_url"] = s3_result["s3_url"]

        # Write to each target cogent's scoped channels
        for cogent_name in targets:
            repo = self._get_repo(cogent_name)
            if not repo:
                continue
            try:
                await self._write_to_cogent(repo, cogent_name, message, message_type, payload)
            except Exception:
                logger.exception("Failed to relay message to cogent %s", cogent_name)

    async def _write_to_cogent(self, repo, cogent_name: str, message, message_type: str, payload: dict):
        """Write a message to a cogent's scoped channels."""
        from cogos.db.models import ChannelMessage

        type_suffix = message_type.split(":")[1]  # dm, mention, message
        channel_name = f"io:discord:{cogent_name}:{type_suffix}"
        ch = self._get_or_create_channel(repo, channel_name)
        if ch is None:
            return

        trace_id = None
        trace_meta = None
        if message_type in ("discord:dm", "discord:mention"):
            from uuid import uuid4
            trace_id = uuid4()
            trace_meta = {
                "discord_created_at_ms": int(message.created_at.timestamp() * 1000),
                "bridge_received_at_ms": int(time.time() * 1000),
            }

        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=None,
            payload=payload,
            idempotency_key=f"discord:{message.id}",
            trace_id=trace_id,
            trace_meta=trace_meta,
        ))

        # Fine-grained per-source channel
        fine_name = None
        if message_type == "discord:message":
            fine_name = f"io:discord:{cogent_name}:message:{payload['channel_id']}"
        elif message_type == "discord:dm":
            fine_name = f"io:discord:{cogent_name}:dm:{payload['author_id']}"
        if fine_name:
            fine_ch = self._get_or_create_channel(repo, fine_name)
            if fine_ch:
                repo.append_channel_message(ChannelMessage(
                    channel=fine_ch.id, sender_process=None, payload=payload,
                ))

        if message_type in ("discord:dm", "discord:mention"):
            self._start_typing(message.channel)

    # -- Outbound: send via webhook --

    async def _send_reply(self, sqs_message: dict):
        """Send a reply using the cogent's webhook."""
        body = json.loads(sqs_message["Body"])
        meta = body.get("_meta", {})
        cogent_name = meta.get("cogent_name", "")

        if not cogent_name:
            logger.warning("Reply missing cogent_name in _meta, discarding")
            return

        persona = self._lifecycle.get_persona(cogent_name)
        msg_type = body.get("type", "message")

        if msg_type == "dm":
            await self._handle_dm(body)
            return

        raw_channel = body.get("channel", "")
        try:
            channel_id = int(raw_channel)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid channel ID: {raw_channel!r}")

        self._stop_typing(channel_id)

        # Try to send via webhook for persona appearance
        if persona and channel_id in persona.webhooks and msg_type == "message":
            await self._handle_webhook_message(body, persona, channel_id)
        else:
            # Fallback to bot user
            channel = self.client.get_channel(channel_id)
            if channel is None:
                channel = await self.client.fetch_channel(channel_id)
            if msg_type == "reaction":
                await self._handle_reaction(body, channel)
            elif msg_type == "thread_create":
                await self._handle_thread_create(body, channel)
            else:
                await self._handle_message(body, channel)

        # Track thread ownership for replies
        thread_id = body.get("thread_id")
        if thread_id and cogent_name:
            self._router.set_thread_owner(int(thread_id), cogent_name)

    async def _handle_webhook_message(self, body: dict, persona, channel_id: int):
        """Send a message via webhook with cogent persona."""
        webhook = persona.webhooks[channel_id]
        content = body.get("content", "")
        if content:
            content = convert_markdown(content)
        thread_id = body.get("thread_id")

        file_specs = body.get("files") or []
        discord_files = await self._download_files(file_specs)

        kwargs = {
            "username": persona.config.display_name,
            "wait": True,
        }
        if persona.config.avatar_url:
            kwargs["avatar_url"] = persona.config.avatar_url
        if thread_id:
            thread = self.client.get_channel(int(thread_id))
            if thread and isinstance(thread, discord.Thread):
                kwargs["thread"] = thread

        if discord_files:
            first_chunk = content[:2000] if content else None
            sent = await webhook.send(content=first_chunk, files=discord_files, **kwargs)
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await webhook.send(content=c, **kwargs)
        elif content:
            chunks = chunk_message(content)
            sent = await webhook.send(content=chunks[0], **kwargs)
            for c in chunks[1:]:
                await webhook.send(content=c, **kwargs)

    # ... (keep _handle_message, _handle_reaction, _handle_thread_create,
    #      _handle_dm, _download_files, _poll_replies largely unchanged,
    #      but _poll_replies uses the new _send_reply which reads cogent_name)

    async def _poll_all_api_requests(self):
        """Poll API request channels for all cogents."""
        seen_requests: dict[str, set[str]] = {}  # cogent_name -> set of seen request ids
        while True:
            for cogent_name in list(self._configs):
                repo = self._get_repo(cogent_name)
                if not repo:
                    continue
                seen = seen_requests.setdefault(cogent_name, set())
                try:
                    await self._poll_api_requests_for_cogent(repo, cogent_name, seen)
                except Exception:
                    logger.exception("API poll error for %s", cogent_name)
            await asyncio.sleep(2)

    async def _poll_api_requests_for_cogent(self, repo, cogent_name: str, seen: set[str]):
        """Poll one cogent's API request channel."""
        ch = self._get_or_create_channel(repo, f"io:discord:{cogent_name}:api:request")
        if ch is None:
            return
        messages = repo.list_channel_messages(ch.id, limit=50)
        for msg in messages:
            msg_id = str(msg.id)
            if msg_id in seen:
                continue
            seen.add(msg_id)
            payload = msg.payload or {}
            request_id = payload.get("request_id", msg_id)
            method = payload.get("method")
            if method == "history":
                try:
                    await self._handle_history_request(repo, cogent_name, payload)
                except Exception:
                    logger.exception("History request failed for %s", cogent_name)
                    self._write_api_response(repo, cogent_name, request_id, "error", error="internal error")
        # Keep seen bounded
        if len(seen) > 1000:
            to_drop = len(seen) - 500
            it = iter(seen)
            for _ in range(to_drop):
                seen.discard(next(it))

    def run(self):
        self.client.run(self.bot_token, log_handler=None)
```

Note: Keep `_make_message_payload`, `_reply_queue_latency_ms`, `_upload_attachment_to_s3`, `_start_typing`, `_stop_typing`, `_handle_message`, `_handle_reaction`, `_handle_thread_create`, `_handle_dm`, `_download_files`, `_get_or_create_channel` from the original — they work the same. The `_get_or_create_channel` and `_write_api_response` just need to accept the scoped channel name.

**Step 2: Run tests**

Run: `python -m pytest tests/ -k discord -v --no-header 2>&1 | head -50`

**Step 3: Commit**

```bash
git add src/cogos/io/discord/bridge.py
git commit -m "feat(discord): rewrite bridge as multi-tenant with webhook personas"
```

---

### Task 6: Update CDK — add shared bridge to polis, remove from cogtainer

**Files:**
- Modify: `src/polis/cdk/stacks/core.py`
- Modify: `src/cogtainer/cdk/stack.py`

**Step 1: Add shared Discord bridge to polis stack**

Add to `PolisStack.__init__` after the CI artifacts bucket:

```python
# --- Shared Discord Bridge ---
self._create_discord_bridge()
```

Add method:

```python
def _create_discord_bridge(self) -> None:
    """Shared Discord bridge Fargate service for all cogents."""
    from aws_cdk import aws_ec2 as ec2, aws_sqs as sqs

    vpc = ec2.Vpc.from_lookup(self, "DiscordVpc", is_default=True)

    # Single SQS queue for all cogent replies
    self.discord_reply_queue = sqs.Queue(
        self,
        "DiscordReplyQueue",
        queue_name="cogent-polis-discord-replies",
        visibility_timeout=Duration.seconds(60),
        retention_period=Duration.days(1),
    )

    # Bot token from Secrets Manager
    bot_token_secret = secretsmanager.Secret.from_secret_name_v2(
        self, "DiscordBotToken",
        secret_name="polis/discord",
    )

    # Sessions bucket for attachments
    sessions_bucket = s3.Bucket.from_bucket_name(
        self, "DiscordSessionsBucket", "cogent-polis-sessions"
    )

    task_def = ecs.FargateTaskDefinition(
        self, "DiscordTaskDef",
        family="cogent-polis-discord",
        cpu=256,
        memory_limit_mib=512,
    )

    task_def.add_container(
        "bridge",
        image=ecs.ContainerImage.from_asset(
            str(SRC_DIR),
            file="src/cogos/io/discord/Dockerfile",
            platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64,
        ),
        environment={
            "DISCORD_REPLY_QUEUE_URL": self.discord_reply_queue.queue_url,
            "DYNAMO_TABLE": self.status_table.table_name,
            "AWS_REGION": config.region,
            "SESSIONS_BUCKET": sessions_bucket.bucket_name,
        },
        secrets={
            "DISCORD_BOT_TOKEN": ecs.Secret.from_secrets_manager(bot_token_secret, field="access_token"),
        },
        logging=ecs.LogDrivers.aws_logs(stream_prefix="discord-bridge"),
    )

    # IAM: DynamoDB (read cogent registry)
    self.status_table.grant_read_data(task_def.task_role)

    # IAM: RDS Data API (all cogent databases)
    task_def.task_role.add_to_policy(
        iam.PolicyStatement(
            actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
            resources=["*"],
        )
    )

    # IAM: Secrets Manager (DB secrets for all cogents)
    task_def.task_role.add_to_policy(
        iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=["*"],
        )
    )

    # IAM: SQS
    self.discord_reply_queue.grant_consume_messages(task_def.task_role)

    # IAM: S3 blob store
    sessions_bucket.grant_read_write(task_def.task_role, "blobs/*")

    sg = ec2.SecurityGroup(self, "DiscordSg", vpc=vpc, allow_all_outbound=True)

    self.discord_service = ecs.FargateService(
        self, "DiscordService",
        service_name="cogent-polis-discord",
        cluster=self.cluster,
        task_definition=task_def,
        desired_count=1,
        assign_public_ip=True,
        security_groups=[sg],
        vpc_subnets=ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        ),
    )

    cdk.CfnOutput(self, "DiscordReplyQueueUrl", value=self.discord_reply_queue.queue_url)
```

**Step 2: Remove Discord bridge from cogtainer stack**

In `src/cogtainer/cdk/stack.py`:

- Remove the call `self._create_discord_bridge(config, safe_name)` (line 110)
- Remove the `_create_discord_bridge` method entirely (lines 161-266)
- Remove `self.compute.executor.add_environment("DISCORD_REPLY_QUEUE_URL", ...)` (lines 113-115)
- Update the status manifest to remove discord service ARN
- Keep the executor env var but point to the polis queue: add `"DISCORD_REPLY_QUEUE_URL"` to executor env pointing to the shared queue URL (can be constructed from account/region or passed as a parameter)

**Step 3: Grant cogtainer executor/orchestrator send access to polis queue**

The executor Lambda and ECS task need permission to send to `cogent-polis-discord-replies`. Add a cross-stack reference or use the queue ARN directly:

```python
# In cogtainer stack, import the polis queue by name
polis_discord_queue = sqs.Queue.from_queue_arn(
    self, "PolisDiscordQueue",
    f"arn:aws:sqs:{config.region}:{config.account}:cogent-polis-discord-replies",
)
polis_discord_queue.grant_send_messages(self.compute.orchestrator)
polis_discord_queue.grant_send_messages(self.compute.executor)
polis_discord_queue.grant_send_messages(self.compute.task_definition.task_role)

self.compute.executor.add_environment("DISCORD_REPLY_QUEUE_URL", polis_discord_queue.queue_url)
```

**Step 4: Commit**

```bash
git add src/polis/cdk/stacks/core.py src/cogtainer/cdk/stack.py
git commit -m "feat(cdk): move Discord bridge to polis, remove per-cogent bridge infra"
```

---

### Task 7: Update Dockerfile and watcher manifest

**Files:**
- Modify: `src/cogos/io/discord/Dockerfile` (if needed — likely unchanged since entry point is the same)
- Modify: `src/polis/watcher/handler.py` — add discord config (display_name, avatar_url, color, default_channels) to the status manifest
- Modify: `src/polis/runtime_status.py` — extract discord persona config from Secrets Manager or stack outputs

**Step 1: Add discord persona config to the watcher**

In the watcher handler, after loading the manifest, check Secrets Manager for `cogent/{name}/discord/persona` containing `{"display_name": "...", "avatar_url": "...", "color": 0, "default_channels": [...]}`. Write this to the DynamoDB item under `manifest.discord`.

**Step 2: Commit**

```bash
git add src/polis/watcher/handler.py src/polis/runtime_status.py
git commit -m "feat(watcher): include discord persona config in cogent status manifest"
```

---

### Task 8: Integration test

**Files:**
- Create: `tests/integration/test_shared_discord_bridge.py`

**Step 1: Write integration test**

Test the routing logic end-to-end with mocked Discord client:

```python
"""Integration test for shared Discord bridge routing."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from cogos.io.discord.registry import CogentDiscordConfig
from cogos.io.discord.lifecycle import LifecycleManager
from cogos.io.discord.router import MessageRouter


@pytest.fixture
def configs():
    return [
        CogentDiscordConfig(cogent_name="dr.alpha", display_name="Dr. Alpha", color=0xFF0000),
        CogentDiscordConfig(cogent_name="luna", display_name="Luna", color=0x0000FF, default_channels=["123"]),
    ]


@pytest.fixture
def router(configs):
    lifecycle = LifecycleManager()
    # Manually set up personas
    from cogos.io.discord.lifecycle import CogentPersona
    for cfg in configs:
        lifecycle._personas[cfg.cogent_name] = CogentPersona(config=cfg, role_id=999)
    return MessageRouter(lifecycle)


def test_route_by_role_mention(router):
    """Messages with role mentions route to the mentioned cogent."""
    msg = MagicMock()
    msg.channel = MagicMock(spec=["id"])  # not a DMChannel
    msg.author.id = 42
    role = MagicMock()
    role.name = "cogent:dr.alpha"
    msg.role_mentions = [role]
    assert router.route(msg) == ["dr.alpha"]


def test_route_dm_last_interaction(router):
    """DMs route to last interacted cogent."""
    import discord
    router.update_last_interaction(42, "luna")
    msg = MagicMock()
    msg.channel = MagicMock(spec=discord.DMChannel)
    msg.channel.__class__ = discord.DMChannel
    msg.author.id = 42
    msg.content = "hello"
    # isinstance check needs special handling in tests
    with patch("cogos.io.discord.router.isinstance", side_effect=lambda obj, cls: cls == discord.DMChannel if cls == discord.DMChannel else builtins_isinstance(obj, cls)):
        result = router.route(msg)
    assert result == ["luna"]


def test_route_channel_default(router):
    """Messages in a default channel route to the owning cogent."""
    msg = MagicMock()
    msg.channel.id = 123
    msg.role_mentions = []
    assert router.route(msg) == ["luna"]


def test_route_no_match(router):
    """Unmatched guild messages return empty list."""
    msg = MagicMock()
    msg.channel.id = 999
    msg.role_mentions = []
    assert router.route(msg) == []
```

**Step 2: Run tests**

Run: `python -m pytest tests/integration/test_shared_discord_bridge.py -v`

**Step 3: Commit**

```bash
git add tests/integration/test_shared_discord_bridge.py
git commit -m "test(discord): add integration tests for shared bridge routing"
```
