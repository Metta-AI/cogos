"""Event capabilities — emit and query events."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.db.models import Event

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class EmitResult(BaseModel):
    id: str
    event_type: str
    created_at: str | None = None


class EventRecord(BaseModel):
    id: str
    event_type: str
    source: str | None = None
    payload: dict[str, Any] = {}
    parent_event: str | None = None
    created_at: str | None = None


class EventError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class EventsCapability(Capability):
    """Append-only event log.

    Usage:
        events.emit("task:completed", {"task_id": "123"})
        events.query("email:received", limit=10)
    """

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        parent_event: str | None = None,
    ) -> EmitResult | EventError:
        if not event_type:
            return EventError(error="event_type is required")

        event = Event(
            event_type=event_type,
            source=f"process:{self.process_id}",
            payload=payload or {},
            parent_event=UUID(parent_event) if parent_event else None,
        )

        event_id = self.repo.append_event(event)

        return EmitResult(
            id=str(event_id),
            event_type=event_type,
            created_at=event.created_at.isoformat() if event.created_at else None,
        )

    def query(self, event_type: str | None = None, limit: int = 100) -> list[EventRecord]:
        events = self.repo.get_events(event_type=event_type, limit=limit)
        return [
            EventRecord(
                id=str(e.id),
                event_type=e.event_type,
                source=e.source,
                payload=e.payload,
                parent_event=str(e.parent_event) if e.parent_event else None,
                created_at=e.created_at.isoformat() if e.created_at else None,
            )
            for e in events
        ]

    def __repr__(self) -> str:
        return "<EventsCapability emit() query()>"
