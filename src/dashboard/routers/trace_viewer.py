"""Trace viewer API — returns full trace with all spans and events."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.db import get_repo

router = APIRouter(tags=["trace-viewer"])


class SpanEventOut(BaseModel):
    id: str
    event: str
    message: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpanOut(BaseModel):
    id: str
    trace_id: str
    parent_span_id: str | None = None
    name: str
    coglet: str | None = None
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEventOut] = Field(default_factory=list)


class TraceSummary(BaseModel):
    total_duration_ms: int | None = None
    total_spans: int = 0
    error_count: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0


class TraceOut(BaseModel):
    id: str
    cogent_id: str
    source: str
    source_ref: str | None = None
    created_at: str | None = None
    spans: list[SpanOut] = Field(default_factory=list)
    summary: TraceSummary


class TraceListItem(BaseModel):
    id: str
    cogent_id: str
    source: str
    source_ref: str | None = None
    created_at: str | None = None
    span_count: int = 0


class TraceListResponse(BaseModel):
    count: int
    traces: list[TraceListItem]


@router.get("/trace-viewer", response_model=TraceListResponse)
def list_traces(name: str, limit: int = 20) -> TraceListResponse:
    repo = get_repo()
    rows = repo.query(
        "SELECT id, cogent_id, source, source_ref, created_at"
        " FROM cogos_request_trace ORDER BY created_at DESC LIMIT :limit",
        {"limit": min(limit, 100)},
    )
    items = []
    for r in rows:
        tid = UUID(r["id"])
        span_count_rows = repo.query(
            "SELECT COUNT(*) AS cnt FROM cogos_span WHERE trace_id = :tid",
            {"tid": tid},
        )
        items.append(TraceListItem(
            id=r["id"],
            cogent_id=r.get("cogent_id", ""),
            source=r.get("source", ""),
            source_ref=r.get("source_ref"),
            created_at=r.get("created_at"),
            span_count=span_count_rows[0]["cnt"] if span_count_rows else 0,
        ))
    return TraceListResponse(count=len(items), traces=items)


@router.get("/trace-viewer/{trace_id}", response_model=TraceOut)
def get_trace(name: str, trace_id: str) -> TraceOut:
    repo = get_repo()
    try:
        tid = UUID(trace_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Invalid trace_id") from err

    trace = repo.get_request_trace(tid)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = repo.list_spans(tid)
    all_events = repo.list_span_events_for_trace(tid)

    events_by_span: dict[UUID, list] = {}
    for evt in all_events:
        events_by_span.setdefault(evt.span_id, []).append(evt)

    span_outs = []
    error_count = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0

    for span in spans:
        duration_ms = None
        if span.started_at and span.ended_at:
            duration_ms = int((span.ended_at - span.started_at).total_seconds() * 1000)

        if span.status.value == "errored":
            error_count += 1

        meta = span.metadata or {}
        total_tokens_in += meta.get("tokens_in", 0)
        total_tokens_out += meta.get("tokens_out", 0)
        total_cost += meta.get("cost_usd", 0.0)

        span_events = [
            SpanEventOut(
                id=str(e.id),
                event=e.event,
                message=e.message,
                timestamp=e.timestamp.isoformat() if e.timestamp else None,
                metadata=e.metadata,
            )
            for e in events_by_span.get(span.id, [])
        ]

        span_outs.append(SpanOut(
            id=str(span.id),
            trace_id=str(span.trace_id),
            parent_span_id=str(span.parent_span_id) if span.parent_span_id else None,
            name=span.name,
            coglet=span.coglet,
            status=span.status.value,
            started_at=span.started_at.isoformat() if span.started_at else None,
            ended_at=span.ended_at.isoformat() if span.ended_at else None,
            duration_ms=duration_ms,
            metadata=meta,
            events=span_events,
        ))

    total_duration_ms = None
    if spans:
        started_times = [s.started_at for s in spans if s.started_at]
        ended_times = [s.ended_at for s in spans if s.ended_at]
        if started_times and ended_times:
            earliest = min(started_times)
            latest = max(ended_times)
            total_duration_ms = int((latest - earliest).total_seconds() * 1000)

    return TraceOut(
        id=str(trace.id),
        cogent_id=trace.cogent_id,
        source=trace.source,
        source_ref=trace.source_ref,
        created_at=trace.created_at.isoformat() if trace.created_at else None,
        spans=span_outs,
        summary=TraceSummary(
            total_duration_ms=total_duration_ms,
            total_spans=len(spans),
            error_count=error_count,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_cost_usd=total_cost,
        ),
    )
