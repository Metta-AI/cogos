"""ProcessHandle — universal interface for interacting with a process."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cogos.db.models import Channel, ChannelMessage, ProcessStatus


class MessageInfo(BaseModel):
    id: str
    payload: dict[str, Any]
    sender_process: str
    created_at: str | None = None


class RunInfo(BaseModel):
    status: str
    error: str | None = None
    duration_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    result: dict[str, Any] | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ProcessHandle:
    """Handle to a process with send/recv/kill/status/wait/wait_any/wait_all/schema."""

    def __init__(
        self,
        repo,
        caller_process_id: UUID,
        process,
        send_channel: Channel | None,
        recv_channel: Channel | None,
    ):
        self._repo = repo
        self._caller_id = caller_process_id
        self._process = process
        self._send_channel = send_channel
        self._recv_channel = recv_channel

    @property
    def id(self) -> str:
        return str(self._process.id)

    @property
    def name(self) -> str:
        return self._process.name

    @property
    def channel(self) -> Channel | None:
        """The recv channel (child->parent for spawn, topic for lookup)."""
        return self._recv_channel

    def send(self, payload: dict[str, Any]) -> dict:
        """Send a message on the parent->child channel."""
        if self._send_channel is None:
            return {"error": "No send channel available for this process"}
        msg = ChannelMessage(
            channel=self._send_channel.id,
            sender_process=self._caller_id,
            payload=payload,
        )
        msg_id = self._repo.append_channel_message(msg)
        return {"id": str(msg_id), "channel": self._send_channel.name}

    def recv(self, limit: int = 10) -> list[MessageInfo]:
        """Read messages from the child->parent channel."""
        if self._recv_channel is None:
            return []
        msgs = self._repo.list_channel_messages(self._recv_channel.id, limit=limit)
        return [
            MessageInfo(
                id=str(m.id),
                payload=m.payload,
                sender_process=str(m.sender_process),
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in msgs
        ]

    def kill(self) -> dict:
        """Shut down the process."""
        proc = self._repo.get_process(self._process.id)
        if proc is None:
            return {"error": "Process not found"}
        prev = proc.status.value
        self._repo.update_process_status(self._process.id, ProcessStatus.DISABLED)
        return {"process_id": self.id, "previous_status": prev, "new_status": "disabled"}

    def status(self) -> str:
        """Get current process status."""
        proc = self._repo.get_process(self._process.id)
        if proc is None:
            return "unknown"
        return proc.status.value

    def schema(self) -> dict[str, Any] | None:
        """Get the schema for this process's channels."""
        if self._send_channel and self._send_channel.inline_schema:
            return self._send_channel.inline_schema
        if self._send_channel and self._send_channel.schema_id:
            s = self._repo.get_schema(self._send_channel.schema_id)
            return s.definition if s else None
        return None

    def wait(self) -> dict:
        """Return a wait spec -- the executor interprets this to end the run and re-wake when child completes."""
        return {"type": "wait", "process_ids": [str(self._process.id)]}

    @staticmethod
    def wait_any(handles: list[ProcessHandle]) -> dict:
        return {"type": "wait_any", "process_ids": [h.id for h in handles]}

    @staticmethod
    def wait_all(handles: list[ProcessHandle]) -> dict:
        return {"type": "wait_all", "process_ids": [h.id for h in handles]}

    def cog_send(self, payload: dict[str, Any]) -> dict:
        """Send a message to the child via cog:from channel (injected into its context)."""
        ch = self._repo.get_channel_by_name(f"cog:from:{self._process.name}")
        if not ch:
            return {"error": f"No cog:from channel for {self._process.name}"}
        msg = ChannelMessage(channel=ch.id, sender_process=self._caller_id, payload=payload)
        msg_id = self._repo.append_channel_message(msg)
        return {"id": str(msg_id), "channel": ch.name}

    def cog_recv(self, limit: int = 10) -> list[MessageInfo]:
        """Read messages from the child's cog:to channel."""
        ch = self._repo.get_channel_by_name(f"cog:to:{self._process.name}")
        if not ch:
            return []
        msgs = self._repo.list_channel_messages(ch.id, limit=limit)
        return [
            MessageInfo(
                id=str(m.id),
                payload=m.payload,
                sender_process=str(m.sender_process),
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in msgs
        ]

    def stdin(self, text: str) -> dict:
        """Write to child's stdin channel."""
        ch = self._repo.get_channel_by_name(f"process:{self._process.name}:stdin")
        if not ch:
            return {"error": f"No stdin channel for {self._process.name}"}
        msg = ChannelMessage(channel=ch.id, sender_process=self._caller_id, payload={"text": text})
        msg_id = self._repo.append_channel_message(msg)
        return {"id": str(msg_id)}

    def stdout(self, limit: int = 1) -> str | list[str] | None:
        """Read from child's stdout channel."""
        ch = self._repo.get_channel_by_name(f"process:{self._process.name}:stdout")
        if not ch:
            return None
        msgs = self._repo.list_channel_messages(ch.id, limit=limit)
        if not msgs:
            return None
        texts = [m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload) for m in msgs]
        return texts[0] if limit == 1 else texts

    def stderr(self, limit: int = 1) -> str | list[str] | None:
        """Read from child's stderr channel."""
        ch = self._repo.get_channel_by_name(f"process:{self._process.name}:stderr")
        if not ch:
            return None
        msgs = self._repo.list_channel_messages(ch.id, limit=limit)
        if not msgs:
            return None
        texts = [m.payload.get("text", "") if isinstance(m.payload, dict) else str(m.payload) for m in msgs]
        return texts[0] if limit == 1 else texts

    def runs(self, limit: int = 10) -> list[RunInfo]:
        """Return recent run history for this process."""
        runs = self._repo.list_runs(process_id=self._process.id, limit=limit)
        return [
            RunInfo(
                status=r.status.value,
                error=r.error,
                duration_ms=r.duration_ms,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                cost_usd=r.cost_usd,
                result=r.result,
                created_at=r.created_at,
                completed_at=r.completed_at,
            )
            for r in runs
        ]

    def __repr__(self) -> str:
        return f"<ProcessHandle {self.name} ({self.id[:8]})>"
