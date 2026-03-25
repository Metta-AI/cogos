"""Trace context propagation via contextvars."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from cogos.db.models.span import Span, SpanEvent
from cogos.db.models.trace import RequestTrace

logger = logging.getLogger(__name__)

_current_trace: ContextVar[TraceContext | None] = ContextVar("_current_trace", default=None)


@dataclass
class TraceContext:
    """Holds the active trace + current span for the executing context."""
    trace_id: UUID
    span_id: UUID
    repo: Any  # Repository — typed as Any to avoid circular import

    def start_span(self, name: str, *, coglet: str | None = None, metadata: dict | None = None) -> SpanContext:
        """Create a child span. Use as a context manager."""
        return SpanContext(
            parent=self,
            name=name,
            coglet=coglet,
            metadata=metadata if metadata is not None else {},
        )

    def log(self, event: str, message: str, metadata: dict | None = None) -> None:
        """Log an event to the current span."""
        try:
            self.repo.create_span_event(SpanEvent(
                span_id=self.span_id,
                event=event,
                message=message,
                metadata=metadata if metadata is not None else {},
            ))
        except Exception:
            logger.debug("Failed to log span event", exc_info=True)

    def serialize(self) -> dict[str, str]:
        """Serialize for cross-process propagation."""
        return {
            "trace_id": str(self.trace_id),
            "span_id": str(self.span_id),
        }


class SpanContext:
    """Context manager that creates a child span and restores parent on exit."""

    def __init__(
        self,
        parent: TraceContext,
        name: str,
        coglet: str | None,
        metadata: dict,
    ) -> None:
        self._parent = parent
        self._name = name
        self._coglet = coglet
        self._metadata = metadata
        self._span_id = uuid4()
        self._token = None

    def __enter__(self) -> TraceContext:
        span = Span(
            id=self._span_id,
            trace_id=self._parent.trace_id,
            parent_span_id=self._parent.span_id,
            name=self._name,
            coglet=self._coglet,
            metadata=self._metadata,
        )
        try:
            self._parent.repo.create_span(span)
        except Exception:
            logger.debug("Failed to create span %s", self._name, exc_info=True)

        child_ctx = TraceContext(
            trace_id=self._parent.trace_id,
            span_id=self._span_id,
            repo=self._parent.repo,
        )
        self._token = _current_trace.set(child_ctx)
        return child_ctx

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        status = "errored" if exc_type else "completed"
        extra_meta = {}
        if exc_val:
            extra_meta["error"] = str(exc_val)[:1000]
        try:
            self._parent.repo.complete_span(
                self._span_id,
                status=status,
                metadata=extra_meta or None,
            )
        except Exception:
            logger.debug("Failed to complete span %s", self._name, exc_info=True)

        if self._token is not None:
            _current_trace.reset(self._token)


def current_trace() -> TraceContext | None:
    """Get the current trace context, if any."""
    return _current_trace.get()


def init_trace(
    repo,
    *,
    trace_id: UUID | None = None,
    parent_span_id: UUID | None = None,
    source: str = "",
    source_ref: str | None = None,
    cogent_id: str = "",
) -> TraceContext:
    """Initialize a new trace or continue an existing one.

    - If trace_id is None, creates a new RequestTrace in the DB.
    - If trace_id is provided, continues that trace (cross-process).
    - Always creates a root span for this process.

    Returns the TraceContext and sets it as the current context.
    """
    if trace_id is None:
        trace_id = uuid4()
    # Ensure the RequestTrace row exists (required by cogos_span FK).
    # This is idempotent — a duplicate insert is harmlessly ignored.
    try:
        repo.create_request_trace(RequestTrace(
            id=trace_id,
            cogent_id=cogent_id,
            source=source,
            source_ref=source_ref,
        ))
    except Exception:
        logger.debug("Failed to create request trace", exc_info=True)

    root_span_id = uuid4()
    ctx = TraceContext(trace_id=trace_id, span_id=root_span_id, repo=repo)

    span = Span(
        id=root_span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        name="root",
        metadata={"source": source},
    )
    try:
        repo.create_span(span)
    except Exception:
        logger.debug("Failed to create root span", exc_info=True)

    _current_trace.set(ctx)
    return ctx
