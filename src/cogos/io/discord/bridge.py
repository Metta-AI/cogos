"""Discord bridge: multi-tenant gateway relay for all cogents.

Runs as a single Fargate service. Connects to the Discord gateway once,
routes inbound messages to per-cogent DB channels via MessageRouter,
and long-polls a shared SQS queue for outbound replies sent via webhooks.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time

import aiohttp
import discord

from cogos.io.discord.chunking import chunk_message
from cogos.io.discord.lifecycle import CogentPersona, LifecycleManager
from cogos.io.discord.markdown import convert_markdown
from cogos.io.discord.registry import CogentDiscordConfig, load_cogent_configs
from cogos.io.discord.router import MessageRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message payload builder (pure utility — unchanged)
# ---------------------------------------------------------------------------


def _make_message_payload(
    message: discord.Message,
    message_type: str,
    *,
    is_dm: bool,
    is_mention: bool,
) -> dict:
    """Build the cogos message payload from a Discord message."""
    attachments = []
    for a in message.attachments:
        attachments.append(
            {
                "url": a.url,
                "filename": a.filename,
                "content_type": a.content_type,
                "size": a.size,
                "is_image": a.content_type.startswith("image/") if a.content_type else False,
                "width": a.width,
                "height": a.height,
            }
        )

    thread_id = None
    parent_channel_id = None
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)
        parent_channel_id = str(message.channel.parent_id)

    embeds = []
    for e in message.embeds:
        embed_data: dict = {"type": e.type}
        if e.title:
            embed_data["title"] = e.title
        if e.description:
            embed_data["description"] = e.description
        if e.url:
            embed_data["url"] = e.url
        if e.image:
            embed_data["image_url"] = e.image.url
        embeds.append(embed_data)

    return {
        "content": message.content,
        "author": str(message.author),
        "author_id": str(message.author.id),
        "channel_id": str(message.channel.id),
        "channel_name": getattr(message.channel, "name", None) or "",
        "guild_id": str(message.guild.id) if message.guild else None,
        "message_id": str(message.id),
        "message_type": message_type,
        "timestamp": message.created_at.isoformat(),
        "is_dm": is_dm,
        "is_mention": is_mention,
        "attachments": attachments,
        "thread_id": thread_id,
        "parent_channel_id": parent_channel_id,
        "embeds": embeds,
        "reference_message_id": (
            str(message.reference.message_id) if message.reference else None
        ),
    }


def _reply_queue_latency_ms(body: dict) -> int | None:
    meta = body.get("_meta")
    if not isinstance(meta, dict):
        return None
    queued_at_ms = meta.get("queued_at_ms")
    if isinstance(queued_at_ms, str):
        if not queued_at_ms.isdigit():
            return None
        queued_at_ms = int(queued_at_ms)
    if not isinstance(queued_at_ms, int):
        return None
    return max(0, int(time.time() * 1000) - queued_at_ms)


def _fetch_bot_token_from_secrets(secrets_provider) -> str:
    """Fetch the Discord bot token from cogtainer-level secret."""
    try:
        raw = secrets_provider.cogtainer_secret("discord")
        secret = json.loads(raw)
        token = secret.get("bot_token") or secret.get("access_token", "")
        if token:
            logger.info("Loaded Discord bot token from cogtainer secret")
            return token
    except Exception:
        logger.debug("Could not fetch bot token from cogtainer secret", exc_info=True)
    return ""


# ---------------------------------------------------------------------------
# Multi-tenant Bridge class
# ---------------------------------------------------------------------------


class DiscordBridge:
    """Multi-tenant relay: routes Discord messages to per-cogent DBs
    and sends outbound replies via cogent-specific webhooks."""

    cogent_name: str
    _repo: object | None

    def __init__(self, *, runtime=None):
        from cogtainer.runtime.factory import create_executor_runtime
        self._runtime = runtime or create_executor_runtime()

        self._secrets_provider = self._runtime.get_secrets_provider()
        self.bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if not self.bot_token:
            self.bot_token = _fetch_bot_token_from_secrets(self._secrets_provider)
        if not self.bot_token:
            raise RuntimeError(
                "No Discord token found. Set DISCORD_BOT_TOKEN env var "
                "or store bot_token in cogtainer/discord secret."
            )

        self.reply_queue_url = os.environ.get(
            "DISCORD_REPLY_QUEUE_URL",
            os.environ.get("REPLY_QUEUE_URL", ""),
        )
        self.region = os.environ.get("AWS_REGION", "us-east-1")

        self._sqs_client = self._runtime.get_sqs_client(self.region)
        from cogos import get_sessions_bucket, get_sessions_prefix
        self._blob_bucket = get_sessions_bucket()
        self._blob_prefix = get_sessions_prefix()
        self._s3_client = self._runtime.get_s3_client(self.region) if self._blob_bucket else None

        # Per-cogent state
        self._configs: dict[str, CogentDiscordConfig] = {}  # cogent_name -> config
        self._repos: dict[str, object] = {}  # cogent_name -> repository (lazy)
        self._lifecycle = LifecycleManager()
        self._router = MessageRouter(self._lifecycle)

        # Typing indicator tasks keyed by channel_id
        self._typing_tasks: dict[int, asyncio.Task] = {}

        # Pending DM tracker: dm_channel_id -> (message_id, author_id, received_at, cogent_name)
        self._pending_dms: dict[str, tuple[str, str, float, str]] = {}
        self._alerted_dm_ids: set[str] = set()

        # Track which webhook/bot sent which message for reaction routing
        self._sent_message_owners: dict[int, str] = {}  # discord_message_id -> cogent_name

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guilds = True
        intents.reactions = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    # ------------------------------------------------------------------
    # Per-cogent repository management
    # ------------------------------------------------------------------

    _REPO_FAILED = object()  # sentinel for repos that failed to connect

    def _get_repo(self, cogent_name: str):
        """Get or create a repository for the given cogent. Returns None if no DB config."""
        cached = self._repos.get(cogent_name)
        if cached is self._REPO_FAILED:
            return None
        if cached is not None:
            return cached

        cfg = self._configs.get(cogent_name)
        if cfg is None or not cfg.db_resource_arn:
            self._repos[cogent_name] = self._REPO_FAILED
            return None

        from cogos.db.factory import create_repository

        try:
            repo = create_repository(
                resource_arn=cfg.db_resource_arn,
                secret_arn=cfg.db_secret_arn,
                database=cfg.db_name,
                client=self._runtime.get_rds_data_client(),
            )
            # Verify the schema exists with a quick probe
            repo.get_channel_by_name("__probe__")
        except Exception:
            logger.warning("DB unavailable for cogent %s, skipping", cogent_name, exc_info=True)
            self._repos[cogent_name] = self._REPO_FAILED
            return None
        self._repos[cogent_name] = repo
        return repo

    def _create_alert(
        self, cogent_name: str, severity: str, alert_type: str, message: str, metadata: dict | None = None
    ) -> None:
        """Create an alert in the cogent's DB (best-effort, never raises)."""
        try:
            repo = self._get_repo(cogent_name)
            repo.create_alert(
                severity=severity,
                alert_type=alert_type,
                source=f"discord:bridge:{cogent_name}",
                message=message,
                metadata=metadata or {},
            )
        except Exception:
            logger.exception("Failed to create alert for %s: %s %s", cogent_name, alert_type, message)

    def _create_alert_any(self, severity: str, alert_type: str, message: str, metadata: dict | None = None) -> None:
        """Create an alert in ALL cogent DBs (best-effort)."""
        for cogent_name in self._configs:
            self._create_alert(cogent_name, severity, alert_type, message, metadata)

    # ------------------------------------------------------------------
    # Cogent sync
    # ------------------------------------------------------------------

    async def _sync_cogents(self) -> None:
        """Load configs from DynamoDB, sync roles/webhooks in all guilds."""
        loop = asyncio.get_event_loop()
        sp = self._secrets_provider
        ddb = self._runtime.get_dynamodb_resource()
        configs = await loop.run_in_executor(
            None, lambda: load_cogent_configs(secrets_provider=sp, dynamodb_resource=ddb),
        )

        # Update local config cache (and invalidate repos for changed configs)
        new_config_map: dict[str, CogentDiscordConfig] = {}
        for cfg in configs:
            new_config_map[cfg.cogent_name] = cfg
            old = self._configs.get(cfg.cogent_name)
            if old and (
                old.db_resource_arn != cfg.db_resource_arn
                or old.db_secret_arn != cfg.db_secret_arn
                or old.db_name != cfg.db_name
            ):
                self._repos.pop(cfg.cogent_name, None)

        # Remove repos for cogents that no longer exist
        for name in list(self._repos.keys()):
            if name not in new_config_map:
                self._repos.pop(name, None)

        self._configs = new_config_map
        logger.info("Loaded %d cogent configs: %s", len(configs), list(new_config_map.keys()))

        # Sync roles/webhooks in each guild
        for guild in self.client.guilds:
            try:
                await self._lifecycle.sync(guild, configs)
            except Exception:
                logger.exception("Failed to sync lifecycle for guild %s", guild.name)

    async def _periodic_sync(self) -> None:
        """Re-sync cogent configs every 60 seconds."""
        while True:
            await asyncio.sleep(60)
            try:
                await self._sync_cogents()
            except Exception:
                logger.exception("Periodic cogent sync failed")

    # ------------------------------------------------------------------
    # Guild metadata sync (to each cogent's DB)
    # ------------------------------------------------------------------

    async def _sync_guild(self, guild) -> None:
        """Sync a guild and its channels to every cogent's DB."""
        from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild

        channels = [
            DiscordChannel(
                channel_id=str(ch.id),
                guild_id=str(guild.id),
                name=ch.name,
                topic=getattr(ch, "topic", None),
                category=ch.category.name if ch.category else None,
                channel_type=ch.type.name,
                position=ch.position,
            )
            for ch in guild.channels
        ]

        for cogent_name in self._configs:
            guild_model = DiscordGuild(
                guild_id=str(guild.id),
                cogent_name=cogent_name,
                name=guild.name,
                icon_url=guild.icon.url if guild.icon else None,
                member_count=guild.member_count,
            )

            def _do_sync(cn=cogent_name, gm=guild_model, chs=channels):
                repo = self._get_repo(cn)
                if repo is None:
                    return
                repo.upsert_discord_guild(gm)
                for ch in chs:
                    repo.upsert_discord_channel(ch)

            try:
                await asyncio.get_event_loop().run_in_executor(None, _do_sync)
            except Exception:
                logger.exception("Failed to sync guild %s for cogent %s", guild.name, cogent_name)

        logger.info("Synced guild %s (%d channels) to %d cogents", guild.name, len(channels), len(self._configs))

    async def _on_channel_delete(self, channel) -> None:
        channel_id = str(channel.id)
        for cogent_name in self._configs:
            def _do_delete(cn=cogent_name):
                repo = self._get_repo(cn)
                repo.delete_discord_channel(channel_id)
            try:
                await asyncio.get_event_loop().run_in_executor(None, _do_delete)
            except Exception:
                logger.exception("Failed to delete channel %s for cogent %s", channel_id, cogent_name)

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    def _setup_handlers(self):
        @self.client.event
        async def on_ready():
            logger.info("Discord bridge connected as %s (multi-tenant)", self.client.user)
            await self._sync_cogents()
            for guild in self.client.guilds:
                await self._sync_guild(guild)
            self.client.loop.create_task(self._poll_replies())
            self.client.loop.create_task(self._poll_all_api_requests())
            self.client.loop.create_task(self._check_pending_dms())
            self.client.loop.create_task(self._periodic_sync())

        @self.client.event
        async def on_guild_channel_create(channel):
            await self._sync_guild(channel.guild)

        @self.client.event
        async def on_guild_channel_update(before, after):
            await self._sync_guild(after.guild)

        @self.client.event
        async def on_guild_channel_delete(channel):
            await self._on_channel_delete(channel)

        @self.client.event
        async def on_guild_join(guild):
            await self._sync_cogents()
            await self._sync_guild(guild)

        @self.client.event
        async def on_guild_remove(guild):
            for cogent_name in self._configs:
                try:
                    repo = self._get_repo(cogent_name)
                    repo.delete_discord_guild(str(guild.id))
                except Exception:
                    logger.exception("Failed to delete guild %s for cogent %s", guild.id, cogent_name)

        @self.client.event
        async def on_message(message: discord.Message):
            logger.info(
                "on_message from %s (bot=%s) in %s: %s",
                message.author, message.author.bot, message.channel,
                message.content[:80] if message.content else "(empty)",
            )
            # Ignore our own messages and any other bot messages
            if message.author == self.client.user:
                return
            if message.author.bot:
                return
            await self._relay_to_db(message)

        @self.client.event
        async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
            await self._on_raw_reaction_add(payload)

    # ------------------------------------------------------------------
    # Channel helper
    # ------------------------------------------------------------------

    def _get_or_create_channel(self, repo, channel_name: str):
        """Look up a channel by name, creating it if missing."""
        from cogos.db.models import Channel, ChannelType
        ch = repo.get_channel_by_name(channel_name)
        if ch is None:
            logger.info("Creating channel %s", channel_name)
            ch = Channel(name=channel_name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(ch)
            ch = repo.get_channel_by_name(channel_name)
        return ch

    # ------------------------------------------------------------------
    # Inbound routing
    # ------------------------------------------------------------------

    def _write_to_cogent(
        self,
        cogent_name: str,
        payload: dict,
        message_type: str,
        *,
        trace_id=None,
        trace_meta: dict | None = None,
        discord_message_id: str = "",
    ) -> None:
        """Write an inbound message to a specific cogent's scoped channels."""
        from cogos.db.models import ChannelMessage

        repo = self._get_repo(cogent_name)
        if repo is None:
            logger.warning("No DB for cogent %s, dropping message", cogent_name)
            return

        # Scoped catch-all channel: io:discord:{cogent_name}:{dm|mention|message}
        type_suffix = message_type.split(":")[1]  # dm, mention, message
        channel_name = f"io:discord:{cogent_name}:{type_suffix}"
        ch = self._get_or_create_channel(repo, channel_name)
        if ch is None:
            raise RuntimeError(f"Failed to create channel {channel_name}")

        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=None,
            payload=payload,
            idempotency_key=f"discord:{discord_message_id}" if discord_message_id else None,
            trace_id=trace_id,
            trace_meta=trace_meta,
        ))

        # Stamp db_written_at after successful insert
        if trace_meta is not None:
            trace_meta["db_written_at_ms"] = int(time.time() * 1000)

        logger.info(
            "Wrote %s from %s to %s (cogent=%s)",
            message_type, payload.get("author"), channel_name, cogent_name,
        )

        # Write to fine-grained per-source channel
        fine_channel_name = None
        if message_type == "discord:message":
            fine_channel_name = f"io:discord:{cogent_name}:message:{payload['channel_id']}"
        elif message_type == "discord:dm":
            fine_channel_name = f"io:discord:{cogent_name}:dm:{payload['author_id']}"

        if fine_channel_name:
            fine_ch = self._get_or_create_channel(repo, fine_channel_name)
            if fine_ch:
                repo.append_channel_message(ChannelMessage(
                    channel=fine_ch.id,
                    sender_process=None,
                    payload=payload,
                ))

    async def _relay_to_db(self, message: discord.Message):
        """Route a Discord message to target cogent(s) and write to their DBs."""
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

        if is_dm:
            message_type = "discord:dm"
        elif is_mention:
            message_type = "discord:mention"
        else:
            message_type = "discord:message"

        payload = _make_message_payload(message, message_type, is_dm=is_dm, is_mention=is_mention)

        # Upload attachments to S3
        if self._s3_client and payload.get("attachments"):
            for att_payload, att_obj in zip(payload["attachments"], message.attachments, strict=False):
                s3_result = await self._upload_attachment_to_s3(att_obj)
                if s3_result:
                    att_payload["s3_key"] = s3_result["s3_key"]
                    att_payload["s3_url"] = s3_result["s3_url"]

        # Route to cogent(s)
        targets = self._router.route(message)

        # DM with no target: reply with available cogent list
        if not targets and is_dm:
            available = self._router.available_cogents()
            if available:
                names = ", ".join(f"**{n}**" for n in available)
                await message.channel.send(
                    f"I'm not sure who you'd like to talk to. Available cogents: {names}\n"
                    f"Just type a name to switch, e.g. `{available[0]}`"
                )
            else:
                await message.channel.send("No cogents are currently available.")
            return

        # For non-DM messages with no specific target, this is a regular guild
        # message that no cogent claims. Still write to all cogents as a passive
        # message channel event.
        if not targets and not is_dm:
            targets = list(self._configs.keys())
            # Only write to cogents whose default channels include this channel
            # or if it's a mention (which should always have a target via role).
            # For truly unrouted guild messages, skip to avoid noise.
            if message_type == "discord:message":
                # Only write to cogents that have this channel as default
                filtered = []
                channel_id = str(message.channel.id)
                for name in targets:
                    persona = self._lifecycle.get_persona(name)
                    if persona and channel_id in persona.default_channels:
                        filtered.append(name)
                targets = filtered

        if not targets:
            return

        # Generate trace for DMs and mentions
        trace_id = None
        trace_meta = None
        if message_type in ("discord:dm", "discord:mention"):
            from uuid import uuid4
            bridge_received_at_ms = int(time.time() * 1000)
            trace_id = uuid4()
            trace_meta = {
                "discord_created_at_ms": int(message.created_at.timestamp() * 1000),
                "bridge_received_at_ms": bridge_received_at_ms,
            }

        for cogent_name in targets:
            try:
                self._write_to_cogent(
                    cogent_name,
                    payload,
                    message_type,
                    trace_id=trace_id,
                    trace_meta=trace_meta,
                    discord_message_id=str(message.id),
                )

                # Start typing and track pending DMs
                if message_type in ("discord:dm", "discord:mention"):
                    self._start_typing(message.channel)
                if message_type == "discord:dm":
                    self._track_pending_dm(
                        payload["channel_id"], payload["message_id"],
                        payload["author_id"], cogent_name,
                    )
            except Exception:
                logger.exception("Failed to write message %s to cogent %s", message.id, cogent_name)
                if message_type in ("discord:dm", "discord:mention"):
                    self._create_alert(
                        cogent_name,
                        "critical",
                        "discord:inbound_relay_failed",
                        f"Failed to relay inbound {message_type} from {message.author} to DB — message will be lost",
                        {"message_id": str(message.id), "author": str(message.author), "message_type": message_type},
                    )

    # ------------------------------------------------------------------
    # Reaction relay
    # ------------------------------------------------------------------

    async def _on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Relay reactions on bot/webhook messages to the owning cogent's DB."""
        # Ignore bot reactions
        if payload.member and payload.member.bot:
            return
        if payload.user_id == self.client.user.id:
            return

        try:
            channel = self.client.get_channel(payload.channel_id)
            if channel is None:
                channel = await self.client.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            logger.debug("Could not fetch message %s for reaction relay", payload.message_id, exc_info=True)
            return

        # Determine owning cogent: check sent_message_owners first, then
        # check if it's our bot user, or a webhook message
        owner = self._sent_message_owners.get(payload.message_id)

        if not owner:
            # Check if it's a message from our bot
            if message.author.id == self.client.user.id:
                # Could be any cogent; relay to all
                owner = None
            elif message.webhook_id:
                # Try to match webhook to a cogent persona
                for name, persona in self._lifecycle.personas.items():
                    for wh in persona.webhooks.values():
                        if wh.id == message.webhook_id:
                            owner = name
                            break
                    if owner:
                        break

        reaction_payload = {
            "message_id": str(payload.message_id),
            "channel_id": str(payload.channel_id),
            "reactor_id": str(payload.user_id),
            "emoji": str(payload.emoji.name),
            "guild_id": str(payload.guild_id) if payload.guild_id else None,
        }
        idempotency_key = f"reaction:{payload.message_id}:{payload.user_id}:{payload.emoji.name}"

        target_cogents = [owner] if owner else list(self._configs.keys())

        for cogent_name in target_cogents:
            try:
                from cogos.db.models import ChannelMessage

                repo = self._get_repo(cogent_name)
                ch = self._get_or_create_channel(repo, f"io:discord:{cogent_name}:reaction")
                if ch is None:
                    continue

                repo.append_channel_message(ChannelMessage(
                    channel=ch.id,
                    sender_process=None,
                    payload=reaction_payload,
                    idempotency_key=idempotency_key,
                ))
                logger.info(
                    "Relayed reaction %s from user %s on message %s to cogent %s",
                    payload.emoji.name, payload.user_id, payload.message_id, cogent_name,
                )
            except Exception:
                logger.exception("Failed to relay reaction to cogent %s", cogent_name)

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------

    def _start_typing(self, channel: discord.abc.Messageable):
        channel_id = channel.id
        old = self._typing_tasks.pop(channel_id, None)
        if old and not old.done():
            old.cancel()

        async def _keep_typing():
            try:
                async with channel.typing():
                    await asyncio.sleep(300)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Typing indicator error for channel %s", channel_id, exc_info=True)

        self._typing_tasks[channel_id] = asyncio.create_task(_keep_typing())

    def _stop_typing(self, channel_id: int):
        task = self._typing_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # Pending DM timeout monitor
    # ------------------------------------------------------------------

    _DM_TIMEOUT_S = 300  # 5 minutes without a response triggers an alert
    _DM_STALE_S = 3600   # clean up entries after 1 hour

    def _track_pending_dm(self, dm_channel_id: str, message_id: str, author_id: str, cogent_name: str) -> None:
        """Record an inbound DM that expects a response."""
        self._pending_dms[dm_channel_id] = (message_id, author_id, time.time(), cogent_name)

    def _clear_pending_dm(self, channel_id: str) -> None:
        """Clear pending DM when a response is sent to the channel."""
        entry = self._pending_dms.pop(channel_id, None)
        if entry:
            self._alerted_dm_ids.discard(entry[0])

    def _sweep_pending_dms(self) -> None:
        """Check for timed-out or stale pending DMs (called by the periodic loop)."""
        now = time.time()
        for dm_channel_id, (message_id, author_id, received_at, cogent_name) in list(self._pending_dms.items()):
            elapsed = now - received_at
            if elapsed > self._DM_STALE_S:
                del self._pending_dms[dm_channel_id]
                self._alerted_dm_ids.discard(message_id)
            elif elapsed > self._DM_TIMEOUT_S and message_id not in self._alerted_dm_ids:
                self._alerted_dm_ids.add(message_id)
                self._create_alert(
                    cogent_name,
                    "warning",
                    "discord:dm_timeout",
                    f"DM from user {author_id} has had no response for {int(elapsed)}s",
                    {
                        "author_id": author_id, "message_id": message_id,
                        "dm_channel_id": dm_channel_id, "elapsed_s": int(elapsed),
                    },
                )
                logger.warning(
                    "DM timeout: no response to user %s (message %s) after %ds (cogent=%s)",
                    author_id, message_id, int(elapsed), cogent_name,
                )

    async def _check_pending_dms(self):
        """Periodically check for DMs that haven't received a response."""
        while True:
            await asyncio.sleep(60)
            self._sweep_pending_dms()

    # ------------------------------------------------------------------
    # Attachment upload (unchanged)
    # ------------------------------------------------------------------

    MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25MB

    async def _upload_attachment_to_s3(self, attachment) -> dict | None:
        """Download a Discord attachment and upload to S3. Returns s3_key/s3_url dict or None."""
        if not self._s3_client or not self._blob_bucket:
            return None
        if attachment.size and attachment.size > self.MAX_ATTACHMENT_SIZE:
            logger.warning("Skipping oversized attachment %s (%d bytes)", attachment.filename, attachment.size)
            return None

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
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
        full_key = f"{self._blob_prefix}/{s3_key}" if self._blob_prefix else s3_key

        try:
            put_kwargs: dict = {"Bucket": self._blob_bucket, "Key": full_key, "Body": data}
            if attachment.content_type:
                put_kwargs["ContentType"] = attachment.content_type
            self._s3_client.put_object(**put_kwargs)

            s3_url = self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._blob_bucket, "Key": full_key},
                ExpiresIn=7 * 24 * 3600,
            )
            return {"s3_key": s3_key, "s3_url": s3_url}
        except Exception:
            logger.exception("Failed to upload attachment %s to S3", attachment.filename)
            return None

    # ------------------------------------------------------------------
    # SQS reply failure alerting
    # ------------------------------------------------------------------

    def _alert_reply_failure(self, msg: dict, exc: Exception, *, permanent: bool) -> None:
        """Create an alert for a failed SQS reply send attempt."""
        try:
            body = json.loads(msg.get("Body", "{}"))
            meta = body.get("_meta") if isinstance(body.get("_meta"), dict) else {}
            cogent_name = meta.get("cogent_name", "unknown")
            status = getattr(exc, "status", None)
            exc_label = f"{type(exc).__name__}(status={status})" if status else type(exc).__name__
            msg_type = body.get("type", "message")
            self._create_alert(
                cogent_name if cogent_name in self._configs else next(iter(self._configs), "unknown"),
                "warning" if permanent else "critical",
                "discord:send_permanent_failure" if permanent else "discord:send_failed",
                (
                    f"Cannot send {msg_type} — {exc_label}: {exc} (message discarded)"
                    if permanent
                    else f"Failed to send {msg_type} reply — {exc_label}: {exc} — SQS will retry"
                ),
                {
                    "sqs_message_id": msg.get("MessageId"),
                    "msg_type": msg_type,
                    "target": body.get("channel") or body.get("user_id"),
                    "process_id": meta.get("process_id"),
                    "trace_id": meta.get("trace_id"),
                    "cogent_name": cogent_name,
                    "error": str(exc)[:500],
                    "status": status,
                },
            )
        except Exception:
            logger.debug("Failed to create reply-failure alert", exc_info=True)

    # ------------------------------------------------------------------
    # SQS reply poller (shared queue, multi-tenant dispatch)
    # ------------------------------------------------------------------

    async def _poll_replies(self):
        if not self.reply_queue_url:
            logger.warning("No REPLY_QUEUE_URL set, reply polling disabled")
            return

        logger.info("Starting SQS reply poller on %s", self.reply_queue_url)
        loop = asyncio.get_event_loop()

        while True:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self._sqs_client.receive_message(
                        QueueUrl=self.reply_queue_url,
                        MaxNumberOfMessages=10,
                        WaitTimeSeconds=20,
                    ),
                )
                for msg in response.get("Messages", []):
                    try:
                        await self._send_reply(msg)
                    except discord.errors.HTTPException as exc:
                        is_permanent = (
                            isinstance(exc, (discord.errors.NotFound, discord.errors.Forbidden))
                            or (hasattr(exc, "status") and 400 <= exc.status < 500 and exc.status != 429)
                        )
                        if is_permanent:
                            logger.error("Permanent Discord failure for reply %s (discarding): %s", msg.get("MessageId"), exc)
                        else:
                            logger.exception("Transient Discord failure for reply %s: %s", msg.get("MessageId"), exc)
                        self._alert_reply_failure(msg, exc, permanent=is_permanent)
                        if not is_permanent:
                            continue
                    except (ValueError, discord.errors.InvalidData) as exc:
                        logger.error("Permanent failure sending reply %s (discarding): %s", msg.get("MessageId"), exc)
                        self._alert_reply_failure(msg, exc, permanent=True)
                    except Exception as exc:
                        logger.exception("Failed to send reply: %s", msg.get("MessageId"))
                        self._alert_reply_failure(msg, exc, permanent=False)
                        continue
                    try:
                        self._sqs_client.delete_message(
                            QueueUrl=self.reply_queue_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
                    except Exception:
                        logger.exception("Failed to delete SQS message %s", msg.get("MessageId"))
            except Exception:
                logger.exception("Reply poll error")
                await asyncio.sleep(5)

    async def _send_reply(self, sqs_message: dict):
        body = json.loads(sqs_message["Body"])
        # Stamp SQS receive time for trace
        meta = body.get("_meta")
        if isinstance(meta, dict):
            meta["sqs_received_at_ms"] = int(time.time() * 1000)

        # Extract cogent_name from _meta
        cogent_name = meta.get("cogent_name", "") if isinstance(meta, dict) else ""

        msg_type = body.get("type", "message")

        if msg_type == "dm":
            await self._handle_dm(body, cogent_name)
            return

        raw_channel = body.get("channel", "")
        try:
            channel_id = int(raw_channel)
        except (ValueError, TypeError):
            logger.error("Invalid (non-numeric) channel in reply: %r — discarding", raw_channel)
            raise ValueError(f"Invalid channel ID: {raw_channel!r}") from None
        self._stop_typing(channel_id)

        channel = self.client.get_channel(channel_id)
        if channel is None:
            channel = await self.client.fetch_channel(channel_id)
        if channel is None:
            logger.error("Could not find Discord channel %s", channel_id)
            return

        if msg_type == "reaction":
            await self._handle_reaction(body, channel)
        elif msg_type == "thread_create":
            await self._handle_thread_create(body, channel, cogent_name)
        else:
            # Try webhook first, fall back to bot user
            await self._handle_webhook_message(body, channel, cogent_name)

    # ------------------------------------------------------------------
    # Webhook-based message sending
    # ------------------------------------------------------------------

    async def _handle_webhook_message(self, body: dict, channel, cogent_name: str):
        """Send a message via the cogent's webhook (with persona name/avatar).
        Falls back to bot user if no webhook is available."""
        persona = self._lifecycle.get_persona(cogent_name) if cogent_name else None
        webhook = None

        if persona:
            # Get or create webhook for this channel (or parent channel for threads)
            target_channel = channel
            if isinstance(channel, discord.Thread):
                target_channel = self.client.get_channel(channel.parent_id)
                if target_channel is None:
                    target_channel = await self.client.fetch_channel(channel.parent_id)
            if target_channel and hasattr(target_channel, 'webhooks'):
                webhook = await self._lifecycle.get_or_create_webhook(target_channel, cogent_name)

        if webhook:
            await self._send_via_webhook(body, channel, webhook, persona)
        else:
            # Fall back to regular bot message
            await self._handle_message(body, channel, cogent_name)

    async def _send_via_webhook(self, body: dict, channel, webhook: discord.Webhook, persona: CogentPersona):
        """Send content via a webhook with the persona's display name and avatar."""
        content = body.get("content", "")
        if content:
            content = convert_markdown(content)
        file_specs = body.get("files") or []
        thread_id = body.get("thread_id")
        _reply_to = body.get("reply_to")

        # Determine the thread to send in (if any)
        thread = discord.MISSING
        if isinstance(channel, discord.Thread):
            thread = channel
        elif thread_id:
            t = self.client.get_channel(int(thread_id))
            if t is None:
                try:
                    t = await self.client.fetch_channel(int(thread_id))
                except Exception:
                    logger.warning("Could not find thread %s for webhook send", thread_id)
            if t and isinstance(t, discord.Thread):
                thread = t

        discord_files = await self._download_files(file_specs)

        send_kwargs: dict = {
            "username": persona.display_name,
            "avatar_url": persona.avatar_url or discord.MISSING,
            "wait": True,
        }
        if thread is not discord.MISSING:
            send_kwargs["thread"] = thread

        sent_message = None
        if discord_files:
            first_chunk = content[:2000] if content else None
            sent_message = await webhook.send(
                content=first_chunk, files=discord_files, **send_kwargs
            )
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await webhook.send(content=c, **send_kwargs)
        elif content:
            chunks = chunk_message(content)
            sent_message = await webhook.send(content=chunks[0], **send_kwargs)
            for c in chunks[1:]:
                await webhook.send(content=c, **send_kwargs)

        # Track message ownership for reaction routing
        if sent_message:
            self._sent_message_owners[sent_message.id] = persona.cogent_name
            # Keep bounded
            if len(self._sent_message_owners) > 10000:
                oldest_keys = list(self._sent_message_owners.keys())[:5000]
                for k in oldest_keys:
                    del self._sent_message_owners[k]

        # Set thread ownership if replying in a thread
        actual_thread = thread if thread is not discord.MISSING else None
        if actual_thread and isinstance(actual_thread, discord.Thread):
            self._router.set_thread_owner(actual_thread.id, persona.cogent_name)

        await self._maybe_react(sent_message, body)
        self._log_reply_send_latency(body, msg_type="message", target_id=channel.id)
        self._log_trace_summary(body, msg_type="message", target_id=channel.id)
        self._clear_pending_dm(body.get("channel", ""))

    # ------------------------------------------------------------------
    # Fallback message handlers (bot user, no webhook)
    # ------------------------------------------------------------------

    async def _handle_message(self, body: dict, channel, cogent_name: str = ""):
        content = body.get("content", "")
        if content:
            content = convert_markdown(content)
        file_specs = body.get("files") or []
        thread_id = body.get("thread_id")
        reply_to = body.get("reply_to")

        target = channel
        if thread_id:
            thread = self.client.get_channel(int(thread_id))
            if thread is None:
                try:
                    thread = await self.client.fetch_channel(int(thread_id))
                except Exception:
                    logger.warning("Could not find thread %s, falling back to channel", thread_id)
            if thread:
                target = thread

        reference = None
        if reply_to:
            try:
                reference = discord.MessageReference(message_id=int(reply_to), channel_id=target.id)
            except (ValueError, TypeError):
                logger.warning("Invalid reply_to %r, sending without reference", reply_to)

        discord_files = await self._download_files(file_specs)

        sent_message = None
        if discord_files:
            first_chunk = content[:2000] if content else None
            sent_message = await target.send(content=first_chunk, files=discord_files, reference=reference)
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await target.send(c)
        elif content:
            chunks = chunk_message(content)
            sent_message = await target.send(chunks[0], reference=reference)
            for c in chunks[1:]:
                await target.send(c)

        # Track ownership
        if sent_message and cogent_name:
            self._sent_message_owners[sent_message.id] = cogent_name
            if isinstance(target, discord.Thread):
                self._router.set_thread_owner(target.id, cogent_name)

        await self._maybe_react(sent_message, body)
        self._log_reply_send_latency(body, msg_type="message", target_id=target.id)
        self._log_trace_summary(body, msg_type="message", target_id=target.id)
        # Clear pending DM if this reply was to a DM channel
        self._clear_pending_dm(body.get("channel", ""))

    async def _handle_reaction(self, body: dict, channel):
        message_id = body.get("message_id")
        emoji = body.get("emoji")
        if not message_id or not emoji:
            return
        message = await channel.fetch_message(int(message_id))
        await message.add_reaction(emoji)
        self._log_reply_send_latency(body, msg_type="reaction", target_id=channel.id)

    async def _handle_thread_create(self, body: dict, channel, cogent_name: str = ""):
        thread_name = body.get("thread_name", "Thread")
        message_id = body.get("message_id")
        content = body.get("content", "")

        if message_id:
            message = await channel.fetch_message(int(message_id))
            thread = await message.create_thread(name=thread_name)
        else:
            thread = await channel.create_thread(
                name=thread_name, type=discord.ChannelType.public_thread
            )

        # Set thread ownership
        if cogent_name:
            self._router.set_thread_owner(thread.id, cogent_name)

        if content:
            persona = self._lifecycle.get_persona(cogent_name) if cogent_name else None
            webhook = None
            if persona and thread.parent_id:
                webhook = persona.webhooks.get(thread.parent_id)

            if webhook and persona:
                for c in chunk_message(content):
                    await webhook.send(
                        content=c,
                        thread=thread,
                        username=persona.display_name,
                        avatar_url=persona.avatar_url or discord.MISSING,
                    )
            else:
                for c in chunk_message(content):
                    await thread.send(c)

        self._log_reply_send_latency(body, msg_type="thread_create", target_id=channel.id)

    async def _handle_dm(self, body: dict, cogent_name: str = ""):
        user_id = body.get("user_id")
        content = body.get("content", "")
        if not user_id or not content:
            logger.warning("Dropping DM with missing user_id=%s or empty content", user_id)
            return
        user = await self.client.fetch_user(int(user_id))
        dm_channel = await user.create_dm()
        self._stop_typing(dm_channel.id)

        # Update last interaction so future DMs from this user route to this cogent
        if cogent_name:
            self._router.update_last_interaction(int(user_id), cogent_name)

        file_specs = body.get("files") or []
        discord_files = await self._download_files(file_specs)
        sent_message = None
        if discord_files:
            first_chunk = content[:2000] if content else None
            sent_message = await dm_channel.send(content=first_chunk, files=discord_files)
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await dm_channel.send(c)
        else:
            chunks = chunk_message(content)
            sent_message = await dm_channel.send(chunks[0])
            for c in chunks[1:]:
                await dm_channel.send(c)
        await self._maybe_react(sent_message, body)
        self._log_reply_send_latency(body, msg_type="dm", target_id=dm_channel.id)
        self._log_trace_summary(body, msg_type="dm", target_id=dm_channel.id)
        self._clear_pending_dm(str(dm_channel.id))

    # ------------------------------------------------------------------
    # File downloads (unchanged)
    # ------------------------------------------------------------------

    async def _download_files(self, file_specs: list[dict]) -> list[discord.File]:
        if not file_specs:
            return []
        files = []
        # Collect URL-based specs to download with a single session
        url_specs = []
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
            url = spec.get("url")
            if url:
                url_specs.append(spec)

        if url_specs:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                for spec in url_specs:
                    url = spec["url"]
                    filename = spec.get("filename", "file")
                    try:
                        async with session.get(url) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.read()
                            files.append(discord.File(io.BytesIO(data), filename=filename))
                    except Exception:
                        logger.exception("Failed to download file: %s", url)
        return files

    # ------------------------------------------------------------------
    # Latency / trace logging
    # ------------------------------------------------------------------

    def _log_reply_send_latency(self, body: dict, *, msg_type: str, target_id: int | str):
        latency_ms = _reply_queue_latency_ms(body)
        if latency_ms is None:
            return
        meta = body.get("_meta") if isinstance(body.get("_meta"), dict) else {}
        logger.info(
            "CogOS latency discord_queue->send=%sms type=%s target=%s process=%s run=%s trace=%s cogent=%s",
            latency_ms,
            msg_type,
            target_id,
            meta.get("process_id", ""),
            meta.get("run_id", ""),
            meta.get("trace_id", ""),
            meta.get("cogent_name", ""),
        )

    def _log_trace_summary(self, body: dict, *, msg_type: str, target_id: int | str):
        """Log a complete trace summary if _meta contains trace_id."""
        meta = body.get("_meta")
        if not isinstance(meta, dict):
            return
        trace_id = meta.get("trace_id")
        if not trace_id:
            return

        now_ms = int(time.time() * 1000)
        queued_at_ms = meta.get("queued_at_ms")
        sqs_received_at_ms = meta.get("sqs_received_at_ms", now_ms)

        sqs_to_receive_ms = (sqs_received_at_ms - queued_at_ms) if queued_at_ms else None
        receive_to_send_ms = now_ms - sqs_received_at_ms

        logger.info(
            "CogOS trace_complete trace_id=%s type=%s target=%s "
            "process=%s run=%s cogent=%s "
            "sqs_to_receive_ms=%s receive_to_send_ms=%s",
            trace_id,
            msg_type,
            target_id,
            meta.get("process_id", ""),
            meta.get("run_id", ""),
            meta.get("cogent_name", ""),
            sqs_to_receive_ms,
            receive_to_send_ms,
        )

    async def _maybe_react(self, message, body: dict) -> None:
        """Add a reaction to a sent message if the payload contains a 'react' emoji."""
        react = body.get("react")
        if not react or message is None:
            return
        try:
            await message.add_reaction(react)
        except Exception:
            logger.warning("Failed to add reaction %s to message %s", react, message.id, exc_info=True)

    # ------------------------------------------------------------------
    # API request poller (multi-tenant: poll each cogent's channels)
    # ------------------------------------------------------------------

    async def _poll_all_api_requests(self):
        """Poll io:discord:{cogent_name}:api:request for each cogent."""
        logger.info("Starting multi-tenant API request poller")
        seen_requests: dict[str, set[str]] = {}  # cogent_name -> set of seen msg ids

        while True:
            for cogent_name in list(self._configs.keys()):
                try:
                    if cogent_name not in seen_requests:
                        seen_requests[cogent_name] = set()

                    repo = self._get_repo(cogent_name)
                    if repo is None:
                        continue
                    request_channel_name = f"io:discord:{cogent_name}:api:request"
                    ch = self._get_or_create_channel(repo, request_channel_name)
                    if ch is None:
                        continue

                    messages = repo.list_channel_messages(ch.id, limit=50)
                    for msg in messages:
                        msg_id = str(msg.id)
                        if msg_id in seen_requests[cogent_name]:
                            continue
                        seen_requests[cogent_name].add(msg_id)

                        payload = msg.payload or {}
                        request_id = payload.get("request_id", msg_id)
                        method = payload.get("method")

                        if method == "history":
                            try:
                                await self._handle_history_request(repo, cogent_name, payload)
                            except Exception:
                                logger.exception(
                                    "Failed to handle history request %s for cogent %s", request_id, cogent_name
                                )
                                self._write_api_response(
                                    repo, cogent_name, request_id, "error", error="internal error"
                                )
                        else:
                            logger.warning(
                                "Unknown API request method: %s (request_id=%s, cogent=%s)",
                                method, request_id, cogent_name,
                            )
                            self._write_api_response(
                                repo, cogent_name, request_id, "error",
                                error=f"unknown method: {method}",
                            )

                    # Keep seen_requests bounded per cogent
                    if len(seen_requests[cogent_name]) > 1000:
                        to_drop = len(seen_requests[cogent_name]) - 500
                        it = iter(seen_requests[cogent_name])
                        for _ in range(to_drop):
                            seen_requests[cogent_name].discard(next(it))

                except Exception:
                    logger.exception("API request poll error for cogent %s", cogent_name)

            await asyncio.sleep(2)

    async def _handle_history_request(self, repo, cogent_name: str, request: dict):
        """Handle a 'history' API request by fetching messages from Discord."""
        request_id = request.get("request_id", "")
        channel_id = request.get("channel_id")
        limit = request.get("limit", 50)
        before = request.get("before")
        after = request.get("after")

        if not channel_id:
            self._write_api_response(
                repo, cogent_name, request_id, "error", error="missing channel_id"
            )
            return

        # Fetch the Discord channel
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.client.fetch_channel(int(channel_id))
            except Exception:
                self._write_api_response(
                    repo, cogent_name, request_id, "error", error=f"channel {channel_id} not found"
                )
                return

        # Build history kwargs
        kwargs: dict = {"limit": min(int(limit), 100)}
        if before:
            kwargs["before"] = discord.Object(id=int(before))
        if after:
            kwargs["after"] = discord.Object(id=int(after))

        history_messages = []
        async for msg in channel.history(**kwargs):
            payload = _make_message_payload(
                msg,
                "discord:history",
                is_dm=isinstance(msg.channel, discord.DMChannel),
                is_mention=False,
            )
            history_messages.append(payload)

        # Reverse to oldest-first
        history_messages.reverse()

        self._write_api_response(
            repo, cogent_name, request_id, "ok", messages=history_messages
        )

    def _write_api_response(
        self,
        repo,
        cogent_name: str,
        request_id: str,
        status: str,
        *,
        messages: list | None = None,
        error: str | None = None,
    ):
        """Write an API response to io:discord:{cogent_name}:api:response channel."""
        from cogos.db.models import ChannelMessage

        response_channel_name = f"io:discord:{cogent_name}:api:response"
        ch = self._get_or_create_channel(repo, response_channel_name)
        if ch is None:
            logger.error("Failed to create %s channel", response_channel_name)
            return

        payload: dict = {
            "request_id": request_id,
            "status": status,
        }
        if messages is not None:
            payload["messages"] = messages
        if error is not None:
            payload["error"] = error

        repo.append_channel_message(
            ChannelMessage(
                channel=ch.id,
                sender_process=None,
                payload=payload,
            )
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        """Start the Discord gateway connection (blocking)."""
        self.client.run(self.bot_token, log_handler=None)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bridge = DiscordBridge()
    bridge.run()


if __name__ == "__main__":
    main()
