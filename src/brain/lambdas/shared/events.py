"""EventBridge ↔ Event model converters."""

from __future__ import annotations

import json

import boto3

from brain.db.models import Event


def to_eventbridge(event: Event, bus_name: str) -> dict:
    """Convert Event model to EventBridge PutEvents entry."""
    return {
        "Source": f"cogent.{event.source}",
        "DetailType": event.event_type,
        "Detail": json.dumps(
            {
                "event_type": event.event_type,
                "source": event.source,
                "payload": event.payload,
                "parent_event_id": event.parent_event_id,
            }
        ),
        "EventBusName": bus_name,
    }


def from_eventbridge(eb_event: dict) -> Event:
    """Convert EventBridge event dict to Event model."""
    detail = eb_event.get("detail", {})
    if isinstance(detail, str):
        detail = json.loads(detail)
    return Event(
        event_type=detail.get("event_type", eb_event.get("detail-type", "")),
        source=detail.get("source", eb_event.get("source", "")),
        payload=detail.get("payload", {}),
        parent_event_id=detail.get("parent_event_id"),
    )


def put_event(event: Event, bus_name: str) -> None:
    """Publish an event to EventBridge."""
    client = boto3.client("events")
    client.put_events(Entries=[to_eventbridge(event, bus_name)])


def emit_run_result(
    *,
    succeeded: bool,
    run_id: str,
    task_id: str | None,
    source: str,
    parent_event_id: str | None,
    bus_name: str,
    error: str | None = None,
) -> None:
    """Emit run:succeeded or run:failed event for task lifecycle triggers."""
    if not task_id:
        return
    payload: dict = {"run_id": run_id, "task_id": task_id}
    if not succeeded and error:
        payload["error"] = error[:1000]
    put_event(
        Event(
            event_type="run:succeeded" if succeeded else "run:failed",
            source=source,
            payload=payload,
            parent_event_id=parent_event_id,
        ),
        bus_name,
    )
