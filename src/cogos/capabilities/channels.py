"""Channels capability — create, read, write, subscribe to typed channels."""
from __future__ import annotations

import fnmatch
import logging
from typing import Any

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.channels.schema_validator import SchemaValidationError, SchemaValidator
from cogos.db.models import Channel, ChannelMessage, ChannelType, Handler
from cogos.trace import current_trace

logger = logging.getLogger(__name__)

ALL_OPS = {"create", "list", "get", "send", "read", "subscribe", "close"}


# ── IO Models ────────────────────────────────────────────────

class ChannelInfo(BaseModel):
    id: str
    name: str
    channel_type: str
    owner_process: str
    schema_id: str | None = None
    inline_schema: dict[str, Any] | None = None
    auto_close: bool = False
    closed_at: str | None = None
    created_at: str | None = None


class MessageInfo(BaseModel):
    id: str
    channel: str
    sender_process: str
    payload: dict[str, Any]
    created_at: str | None = None


class SendResult(BaseModel):
    id: str
    channel: str


class SubscribeResult(BaseModel):
    handler_id: str
    channel: str


class ChannelError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class ChannelsCapability(Capability):
    """Named topic channels for inter-process communication.

    Usage:
        channels.create("metrics", schema={"value": "number"})
        channels.send("metrics", {"value": 42})
        channels.read("metrics", limit=10)
        channels.subscribe("metrics")
        channels.list()
        channels.get("metrics")
        channels.close("metrics")
    """

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        # Narrow ops
        old_ops = set(existing.get("ops") or ALL_OPS)
        new_ops = set(requested.get("ops") or ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        # Narrow name patterns
        for key in ("names",):
            old = existing.get(key)
            new = requested.get(key)
            if old is not None and new is not None:
                if "*" in old:
                    result[key] = new
                elif "*" in new:
                    result[key] = old
                else:
                    result[key] = [p for p in old if p in new]
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        # Check op
        allowed_ops = set(self._scope.get("ops") or ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})")
        # Check name pattern
        patterns = self._scope.get("names")
        if patterns is None:
            return
        name = context.get("name", "")
        if not name:
            return
        for pattern in patterns:
            if fnmatch.fnmatch(str(name), pattern):
                return
        raise PermissionError(f"Channel '{name}' not permitted; allowed: {patterns}")

    def create(
        self,
        name: str,
        schema: str | dict[str, Any] | None = None,
    ) -> ChannelInfo | ChannelError:
        """Create a named channel."""
        self._check("create", name=name)

        schema_id = None
        inline_schema = None

        if isinstance(schema, str):
            # Named schema reference
            s = self.repo.get_schema_by_name(schema)
            if s is None:
                return ChannelError(error=f"Schema '{schema}' not found")
            schema_id = s.id
        elif isinstance(schema, dict):
            # Inline schema — wrap in {"fields": ...} if not already
            if "fields" not in schema:
                inline_schema = {"fields": schema}
            else:
                inline_schema = schema

        ch = Channel(
            name=name,
            owner_process=self.process_id,
            schema_id=schema_id,
            inline_schema=inline_schema,
            channel_type=ChannelType.NAMED,
        )
        self.repo.upsert_channel(ch)

        return self._channel_info(ch)

    def list(self) -> list[ChannelInfo]:
        """List all channels."""
        self._check("list")
        channels = self.repo.list_channels()
        return [self._channel_info(ch) for ch in channels]

    def get(self, name: str) -> ChannelInfo | ChannelError:
        """Get a channel by name."""
        self._check("get", name=name)
        ch = self.repo.get_channel_by_name(name)
        if ch is None:
            return ChannelError(error=f"Channel '{name}' not found")
        return self._channel_info(ch)

    def send(self, name: str, payload: dict[str, Any]) -> SendResult | ChannelError:
        """Send a message to a channel. Validates against schema."""
        self._check("send", name=name)
        ch = self.repo.get_channel_by_name(name)
        if ch is None:
            return ChannelError(error=f"Channel '{name}' not found")
        if ch.closed_at is not None:
            return ChannelError(error=f"Channel '{name}' is closed")

        # Validate against schema
        schema_def = self._get_schema_definition(ch)
        if schema_def:
            try:
                validator = SchemaValidator(schema_def, schema_registry=self._build_registry())
                validator.validate(payload)
            except SchemaValidationError as e:
                return ChannelError(error=f"Schema validation failed: {e}")

        ctx = current_trace()
        msg = ChannelMessage(
            channel=ch.id,
            sender_process=self.process_id,
            payload=payload,
            trace_id=ctx.trace_id if ctx else None,
            trace_meta=ctx.serialize() if ctx else None,
        )
        msg_id = self.repo.append_channel_message(msg)
        return SendResult(id=str(msg_id), channel=name)

    def read(self, name: str, limit: int = 100) -> list[MessageInfo] | ChannelError:
        """Read messages from a channel."""
        self._check("read", name=name)
        ch = self.repo.get_channel_by_name(name)
        if ch is None:
            return ChannelError(error=f"Channel '{name}' not found")
        msgs = self.repo.list_channel_messages(ch.id, limit=limit)
        return [
            MessageInfo(
                id=str(m.id),
                channel=name,
                sender_process=str(m.sender_process),
                payload=m.payload,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in msgs
        ]

    def subscribe(self, name: str) -> SubscribeResult | ChannelError:
        """Subscribe to a channel (creates handler for push wakeup)."""
        self._check("subscribe", name=name)
        ch = self.repo.get_channel_by_name(name)
        if ch is None:
            return ChannelError(error=f"Channel '{name}' not found")
        h = Handler(process=self.process_id, channel=ch.id)
        hid = self.repo.create_handler(h)
        return SubscribeResult(handler_id=str(hid), channel=name)

    def close(self, name: str) -> ChannelInfo | ChannelError:
        """Close a channel you own."""
        self._check("close", name=name)
        ch = self.repo.get_channel_by_name(name)
        if ch is None:
            return ChannelError(error=f"Channel '{name}' not found")
        if ch.owner_process != self.process_id:
            return ChannelError(error="Only the channel owner can close it")
        self.repo.close_channel(ch.id)
        ch = self.repo.get_channel(ch.id)
        return self._channel_info(ch)

    def schema(self, name: str) -> dict[str, Any] | ChannelError:
        """Get the schema definition for a channel."""
        self._check("get", name=name)
        ch = self.repo.get_channel_by_name(name)
        if ch is None:
            return ChannelError(error=f"Channel '{name}' not found")
        schema_def = self._get_schema_definition(ch)
        if schema_def is None:
            return ChannelError(error=f"Channel '{name}' has no schema")
        return schema_def

    def _get_schema_definition(self, ch: Channel) -> dict[str, Any] | None:
        if ch.inline_schema:
            return ch.inline_schema
        if ch.schema_id:
            s = self.repo.get_schema(ch.schema_id)
            if s:
                return s.definition
        return None

    def _build_registry(self) -> dict[str, dict]:
        """Build schema registry for nested schema references."""
        schemas = self.repo.list_schemas()
        return {s.name: s.definition for s in schemas}

    def _channel_info(self, ch: Channel) -> ChannelInfo:
        return ChannelInfo(
            id=str(ch.id),
            name=ch.name,
            channel_type=ch.channel_type.value,
            owner_process=str(ch.owner_process),
            schema_id=str(ch.schema_id) if ch.schema_id else None,
            inline_schema=ch.inline_schema,
            auto_close=ch.auto_close,
            closed_at=ch.closed_at.isoformat() if ch.closed_at else None,
            created_at=ch.created_at.isoformat() if ch.created_at else None,
        )

    def __repr__(self) -> str:
        return "<ChannelsCapability create() list() get() send() read() subscribe() close() schema()>"
