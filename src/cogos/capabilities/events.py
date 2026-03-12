"""Event capabilities — emit and query events."""

from __future__ import annotations

import fnmatch
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

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        for key in ("emit", "query"):
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
        patterns = self._scope.get(op)
        if patterns is None:
            return
        event_type = context.get("event_type", "")
        if not event_type:
            # No event_type provided but scope restricts this op — deny
            raise PermissionError(
                f"Event type required when '{op}' is scoped; "
                f"allowed patterns: {patterns}"
            )
        for pattern in patterns:
            if fnmatch.fnmatch(str(event_type), pattern):
                return
        raise PermissionError(
            f"Event type '{event_type}' not permitted for '{op}'; "
            f"allowed patterns: {patterns}"
        )

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        parent_event: str | None = None,
    ) -> EmitResult | EventError:
        if not event_type:
            return EventError(error="event_type is required")
        self._check("emit", event_type=event_type)

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

    def _matches_query_scope(self, event_type: str) -> bool:
        """Check if an event type matches the query scope patterns."""
        patterns = self._scope.get("query") if self._scope else None
        if patterns is None:
            return True
        return any(fnmatch.fnmatch(event_type, p) for p in patterns)

    def query(self, event_type: str | None = None, limit: int = 100) -> list[EventRecord]:
        self._check("query", event_type=event_type or "")
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
            if self._matches_query_scope(e.event_type)
        ]

    def __repr__(self) -> str:
        return "<EventsCapability emit() query()>"
