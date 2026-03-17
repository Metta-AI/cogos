from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from cogos.db.models import ChannelMessage, Delivery, Run
from dashboard.db import get_repo

router = APIRouter(tags=["request-flows"])

RequestRange = Literal["1m", "10m", "1h", "24h", "1w"]

_RANGE_TO_DELTA: dict[RequestRange, timedelta] = {
    "1m": timedelta(minutes=1),
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "1w": timedelta(weeks=1),
}

_MAX_FLOW_DEPTH = 12


class RequestMessageOut(BaseModel):
    id: str
    channel_id: str
    channel_name: str
    message_type: str | None = None
    sender_process: str | None = None
    sender_process_name: str | None = None
    payload: dict[str, Any]
    created_at: str | None = None


class RequestFlowNodeOut(BaseModel):
    id: str
    kind: Literal["request", "process"]
    label: str
    depth: int
    status: str
    process_id: str | None = None
    process_name: str | None = None
    run_id: str | None = None
    runner: str | None = None
    handler_id: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    channel_name: str | None = None
    message_type: str | None = None


class RequestFlowEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    message_id: str
    delivery_id: str | None = None
    handler_id: str | None = None
    channel_id: str
    channel_name: str
    message_type: str | None = None
    status: str | None = None
    created_at: str | None = None
    delivered_at: str | None = None


class RequestFlowTimelineEntryOut(BaseModel):
    id: str
    kind: Literal["request_received", "handler_matched", "run_started", "run_completed", "message_emitted"]
    timestamp: str | None = None
    title: str
    detail: str | None = None
    status: str | None = None
    node_id: str | None = None
    edge_id: str | None = None


class RequestFlowOut(BaseModel):
    request_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    method: str | None = None
    path: str | None = None
    total_runs: int
    total_edges: int
    total_messages: int
    root_message: RequestMessageOut
    nodes: list[RequestFlowNodeOut]
    edges: list[RequestFlowEdgeOut]
    timeline: list[RequestFlowTimelineEntryOut]


class RequestFlowsResponse(BaseModel):
    count: int
    flows: list[RequestFlowOut]


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    normalized = _as_utc(dt)
    return normalized.isoformat() if normalized else None


def _message_sort_key(message: ChannelMessage) -> datetime:
    return _as_utc(message.created_at) or datetime.min.replace(tzinfo=timezone.utc)


def _message_type(message: ChannelMessage) -> str | None:
    payload = message.payload or {}
    for key in ("message_type", "type"):
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _request_id(message: ChannelMessage) -> str | None:
    payload = message.payload or {}
    for key in ("request_id", "requestId"):
        value = payload.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _message_out(
    message: ChannelMessage,
    *,
    channel_names: dict[UUID, str],
    process_names: dict[UUID, str],
) -> RequestMessageOut:
    return RequestMessageOut(
        id=str(message.id),
        channel_id=str(message.channel),
        channel_name=channel_names.get(message.channel, str(message.channel)),
        message_type=_message_type(message),
        sender_process=str(message.sender_process) if message.sender_process else None,
        sender_process_name=process_names.get(message.sender_process) if message.sender_process else None,
        payload=message.payload or {},
        created_at=_iso(message.created_at),
    )


def _emitted_messages_for_run(
    run: Run,
    source_message_id: UUID,
    all_messages: list[ChannelMessage],
) -> list[ChannelMessage]:
    if run.created_at is None:
        return []

    start = _as_utc(run.created_at)
    completed = _as_utc(run.completed_at)
    end = completed + timedelta(seconds=5) if completed else None

    emitted = []
    for message in all_messages:
        if message.id == source_message_id:
            continue
        if message.sender_process != run.process:
            continue

        created_at = _as_utc(message.created_at)
        if created_at is None or created_at < start:
            continue
        if end is not None and created_at > end:
            continue

        emitted.append(message)

    emitted.sort(key=_message_sort_key)
    return emitted


def _timeline_timestamp_sort_key(timestamp: str | None) -> tuple[int, str]:
    return (0 if timestamp else 1, timestamp or "")


def _node_sort_key(node: RequestFlowNodeOut) -> tuple[int, str, str]:
    return (node.depth, node.created_at or "", node.id)


def _edge_sort_key(edge: RequestFlowEdgeOut) -> tuple[str, str]:
    return (edge.created_at or edge.delivered_at or "", edge.id)


def _find_run_for_delivery(
    delivery: Delivery,
    *,
    target_process_id: UUID,
    runs_by_id: dict[UUID, Run],
    runs_by_message_process: dict[tuple[UUID, UUID], list[Run]],
) -> Run | None:
    if delivery.run is not None:
        return runs_by_id.get(delivery.run)

    candidates = runs_by_message_process.get((delivery.message, target_process_id), [])
    return candidates[0] if len(candidates) == 1 else None


def _flow_status(nodes: list[RequestFlowNodeOut]) -> str:
    process_nodes = [node for node in nodes if node.kind == "process"]
    statuses = {node.status for node in process_nodes}
    if not process_nodes:
        return "orphaned"
    if "failed" in statuses or "timeout" in statuses:
        return "failed"
    if "running" in statuses or "pending" in statuses or "queued" in statuses:
        return "running"
    return "completed"


def _latest_activity(timeline: list[RequestFlowTimelineEntryOut]) -> datetime | None:
    timestamps = [datetime.fromisoformat(entry.timestamp) for entry in timeline if entry.timestamp]
    return max(timestamps) if timestamps else None


@router.get("/request-flows", response_model=RequestFlowsResponse)
def list_request_flows(
    name: str,
    range: RequestRange = Query("1h"),
    limit: int = Query(30, ge=1, le=100),
) -> RequestFlowsResponse:
    repo = get_repo()
    cutoff = datetime.now(timezone.utc) - _RANGE_TO_DELTA[range]
    fetch_limit = max(limit * 50, 1500)

    processes = repo.list_processes(limit=1000)
    channels = repo.list_channels()
    handlers = repo.list_handlers()
    messages = repo.list_channel_messages(limit=fetch_limit)
    deliveries = repo.list_deliveries(limit=max(fetch_limit * 2, 2000))
    runs = repo.list_runs(limit=max(fetch_limit * 2, 2000))

    process_names = {process.id: process.name for process in processes}
    process_runners = {process.id: process.runner for process in processes}
    channel_names = {channel.id: channel.name for channel in channels}
    handlers_by_id = {handler.id: handler for handler in handlers}
    runs_by_id = {run.id: run for run in runs}

    deliveries_by_message: dict[UUID, list[Delivery]] = {}
    for delivery in deliveries:
        deliveries_by_message.setdefault(delivery.message, []).append(delivery)

    runs_by_message_process: dict[tuple[UUID, UUID], list[Run]] = {}
    for run in runs:
        if run.message is None:
            continue
        runs_by_message_process.setdefault((run.message, run.process), []).append(run)
    for candidates in runs_by_message_process.values():
        candidates.sort(key=lambda run: _as_utc(run.created_at) or datetime.min.replace(tzinfo=timezone.utc))

    request_messages: dict[str, list[ChannelMessage]] = {}
    for message in messages:
        created_at = _as_utc(message.created_at)
        if created_at is not None and created_at < cutoff:
            continue
        request_id = _request_id(message)
        if request_id is None:
            continue
        request_messages.setdefault(request_id, []).append(message)

    root_candidates: list[tuple[str, ChannelMessage]] = []
    for request_id, grouped_messages in request_messages.items():
        grouped_messages.sort(key=_message_sort_key)
        root_message = next((message for message in grouped_messages if message.sender_process is None), grouped_messages[0])
        root_candidates.append((request_id, root_message))

    root_candidates.sort(key=lambda item: _message_sort_key(item[1]), reverse=True)

    flows: list[RequestFlowOut] = []
    for request_id, root_message in root_candidates[:limit]:
        method = root_message.payload.get("method") if isinstance(root_message.payload.get("method"), str) else None
        path = root_message.payload.get("path") if isinstance(root_message.payload.get("path"), str) else None

        request_node_id = f"request:{request_id}"
        request_node = RequestFlowNodeOut(
            id=request_node_id,
            kind="request",
            label=f"{method or 'REQUEST'} {path or request_id}".strip(),
            depth=0,
            status="received",
            created_at=_iso(root_message.created_at),
            channel_name=channel_names.get(root_message.channel, str(root_message.channel)),
            message_type=_message_type(root_message),
        )

        nodes: dict[str, RequestFlowNodeOut] = {request_node_id: request_node}
        edges: dict[str, RequestFlowEdgeOut] = {}
        timeline: dict[str, RequestFlowTimelineEntryOut] = {
            f"request:{root_message.id}": RequestFlowTimelineEntryOut(
                id=f"request:{root_message.id}",
                kind="request_received",
                timestamp=_iso(root_message.created_at),
                title=f"Request received on {channel_names.get(root_message.channel, str(root_message.channel))}",
                detail=f"request_id={request_id}",
                status="received",
                node_id=request_node_id,
            )
        }
        flow_message_ids: set[UUID] = {root_message.id}
        visited_runs: set[UUID] = set()

        def upsert_process_node(
            *,
            delivery: Delivery,
            depth: int,
            run: Run | None,
            process_id: UUID,
        ) -> str:
            if run is not None:
                node_id = f"run:{run.id}"
                existing = nodes.get(node_id)
                if existing is None:
                    nodes[node_id] = RequestFlowNodeOut(
                        id=node_id,
                        kind="process",
                        label=process_names.get(process_id, str(process_id)),
                        depth=depth,
                        status=run.status.value,
                        process_id=str(process_id),
                        process_name=process_names.get(process_id),
                        run_id=str(run.id),
                        runner=process_runners.get(process_id),
                        created_at=_iso(run.created_at),
                        completed_at=_iso(run.completed_at),
                        duration_ms=run.duration_ms,
                        tokens_in=run.tokens_in,
                        tokens_out=run.tokens_out,
                        cost_usd=float(run.cost_usd),
                        error=run.error,
                    )
                else:
                    existing.depth = min(existing.depth, depth)
                return node_id

            node_id = f"pending:{delivery.id}"
            existing = nodes.get(node_id)
            if existing is None:
                nodes[node_id] = RequestFlowNodeOut(
                    id=node_id,
                    kind="process",
                    label=process_names.get(process_id, str(process_id)),
                    depth=depth,
                    status=delivery.status.value,
                    process_id=str(process_id),
                    process_name=process_names.get(process_id),
                    handler_id=str(delivery.handler),
                    created_at=_iso(delivery.created_at),
                )
            else:
                existing.depth = min(existing.depth, depth)
            return node_id

        def walk_message(message: ChannelMessage, source_node_id: str, depth: int) -> None:
            if depth > _MAX_FLOW_DEPTH:
                return

            flow_message_ids.add(message.id)
            if source_node_id != request_node_id:
                timeline.setdefault(
                    f"message:{message.id}",
                    RequestFlowTimelineEntryOut(
                        id=f"message:{message.id}",
                        kind="message_emitted",
                        timestamp=_iso(message.created_at),
                        title=f"Message emitted to {channel_names.get(message.channel, str(message.channel))}",
                        detail=_message_type(message) or str(message.id),
                        node_id=source_node_id,
                    ),
                )

            message_deliveries = sorted(
                deliveries_by_message.get(message.id, []),
                key=lambda delivery: _as_utc(delivery.created_at) or datetime.min.replace(tzinfo=timezone.utc),
            )
            for delivery in message_deliveries:
                handler = handlers_by_id.get(delivery.handler)
                if handler is None:
                    continue

                run = _find_run_for_delivery(
                    delivery,
                    target_process_id=handler.process,
                    runs_by_id=runs_by_id,
                    runs_by_message_process=runs_by_message_process,
                )
                target_node_id = upsert_process_node(
                    delivery=delivery,
                    depth=depth,
                    run=run,
                    process_id=handler.process,
                )

                edge_id = f"delivery:{delivery.id}"
                edges.setdefault(
                    edge_id,
                    RequestFlowEdgeOut(
                        id=edge_id,
                        source=source_node_id,
                        target=target_node_id,
                        message_id=str(message.id),
                        delivery_id=str(delivery.id),
                        handler_id=str(delivery.handler),
                        channel_id=str(message.channel),
                        channel_name=channel_names.get(message.channel, str(message.channel)),
                        message_type=_message_type(message),
                        status=delivery.status.value,
                        created_at=_iso(message.created_at),
                        delivered_at=_iso(delivery.created_at),
                    ),
                )

                timeline.setdefault(
                    f"delivery:{delivery.id}",
                    RequestFlowTimelineEntryOut(
                        id=f"delivery:{delivery.id}",
                        kind="handler_matched",
                        timestamp=_iso(delivery.created_at),
                        title=f"Handler matched for {process_names.get(handler.process, str(handler.process))}",
                        detail=channel_names.get(message.channel, str(message.channel)),
                        status=delivery.status.value,
                        node_id=target_node_id,
                        edge_id=edge_id,
                    ),
                )

                if run is None:
                    continue

                timeline.setdefault(
                    f"run-start:{run.id}",
                    RequestFlowTimelineEntryOut(
                        id=f"run-start:{run.id}",
                        kind="run_started",
                        timestamp=_iso(run.created_at),
                        title=f"Run started: {process_names.get(run.process, str(run.process))}",
                        detail=str(run.id),
                        status=run.status.value,
                        node_id=target_node_id,
                        edge_id=edge_id,
                    ),
                )
                if run.completed_at is not None:
                    timeline.setdefault(
                        f"run-end:{run.id}",
                        RequestFlowTimelineEntryOut(
                            id=f"run-end:{run.id}",
                            kind="run_completed",
                            timestamp=_iso(run.completed_at),
                            title=f"Run finished: {process_names.get(run.process, str(run.process))}",
                            detail=str(run.id),
                            status=run.status.value,
                            node_id=target_node_id,
                            edge_id=edge_id,
                        ),
                    )

                if run.id in visited_runs:
                    continue
                visited_runs.add(run.id)

                for emitted_message in _emitted_messages_for_run(run, message.id, messages):
                    walk_message(emitted_message, target_node_id, depth + 1)

        walk_message(root_message, request_node_id, 1)

        nodes_list = sorted(nodes.values(), key=_node_sort_key)
        edges_list = sorted(edges.values(), key=_edge_sort_key)
        timeline_list = sorted(timeline.values(), key=lambda entry: _timeline_timestamp_sort_key(entry.timestamp))
        status = _flow_status(nodes_list)

        started_at = _as_utc(root_message.created_at)
        completed_at = _latest_activity(timeline_list)
        end_for_duration = completed_at
        if status == "running" and started_at is not None:
            end_for_duration = datetime.now(timezone.utc)
        if status == "orphaned" and started_at is not None:
            end_for_duration = started_at

        duration_ms = None
        if started_at is not None and end_for_duration is not None:
            duration_ms = max(0, int((end_for_duration - started_at).total_seconds() * 1000))

        flows.append(
            RequestFlowOut(
                request_id=request_id,
                status=status,
                started_at=_iso(started_at),
                completed_at=_iso(completed_at) if status != "running" else None,
                duration_ms=duration_ms,
                method=method,
                path=path,
                total_runs=len([node for node in nodes_list if node.run_id]),
                total_edges=len(edges_list),
                total_messages=len(flow_message_ids),
                root_message=_message_out(
                    root_message,
                    channel_names=channel_names,
                    process_names=process_names,
                ),
                nodes=nodes_list,
                edges=edges_list,
                timeline=timeline_list,
            )
        )

    return RequestFlowsResponse(count=len(flows), flows=flows)
