"""ProcessHandle — universal interface for interacting with a process."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cogos.db.models import Channel, ChannelMessage, Handler, ProcessStatus
from cogos.db.models.wait_condition import WaitCondition, WaitConditionType
from cogos.sandbox.executor import WaitSuspend


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
        run_id: UUID | None = None,
    ):
        self._repo = repo
        self._caller_id = caller_process_id
        self._process = process
        self._send_channel = send_channel
        self._recv_channel = recv_channel
        self._run_id = run_id

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

    def _check_not_python(self) -> None:
        caller = self._repo.get_process(self._caller_id)
        if caller and caller.executor == "python":
            raise RuntimeError(
                "wait() cannot be used from Python-executed processes — "
                "Python processes cannot session-resume after WaitSuspend"
            )

    def _child_already_exited(self, child_pid: UUID) -> bool:
        ch = self._repo.get_channel_by_name(f"spawn:{child_pid}\u2192{self._caller_id}")
        if not ch:
            return False
        msgs = self._repo.list_channel_messages(ch.id, limit=50)
        return any(
            isinstance(m.payload, dict) and m.payload.get("type") == "child:exited"
            for m in msgs
        )

    def _ensure_handler(self) -> None:
        if self._recv_channel is None:
            return
        self._repo.create_handler(Handler(
            process=self._caller_id,
            channel=self._recv_channel.id,
        ))

    def wait(self) -> None:
        self._check_not_python()
        if self._child_already_exited(self._process.id):
            return
        if self._run_id is None:
            raise RuntimeError("wait() requires run_id on ProcessHandle")
        self._ensure_handler()
        self._repo.create_wait_condition(WaitCondition(
            run=self._run_id,
            type=WaitConditionType.WAIT,
            pending=[str(self._process.id)],
        ))
        raise WaitSuspend()

    @staticmethod
    def wait_any(handles: list[ProcessHandle]) -> None:
        handles[0]._check_not_python()
        if any(h._child_already_exited(h._process.id) for h in handles):
            return
        repo = handles[0]._repo
        run_id = handles[0]._run_id
        if run_id is None:
            raise RuntimeError("wait_any() requires run_id on ProcessHandle")
        for h in handles:
            h._ensure_handler()
        repo.create_wait_condition(WaitCondition(
            run=run_id,
            type=WaitConditionType.WAIT_ANY,
            pending=[h.id for h in handles],
        ))
        raise WaitSuspend()

    @staticmethod
    def wait_all(handles: list[ProcessHandle]) -> None:
        handles[0]._check_not_python()
        still_pending = [h.id for h in handles if not h._child_already_exited(h._process.id)]
        if not still_pending:
            return
        repo = handles[0]._repo
        run_id = handles[0]._run_id
        if run_id is None:
            raise RuntimeError("wait_all() requires run_id on ProcessHandle")
        for h in handles:
            if h.id in still_pending:
                h._ensure_handler()
        repo.create_wait_condition(WaitCondition(
            run=run_id,
            type=WaitConditionType.WAIT_ALL,
            pending=still_pending,
        ))
        raise WaitSuspend()

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
        ch = self._repo.get_channel_by_name(f"io:stdin:{self._process.name}")
        if not ch:
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
