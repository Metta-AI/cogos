"""Event Dispatcher Lambda: polls proposed events from DB and publishes to EventBridge.

Runs on a schedule (every 1 minute). Picks up events with status='proposed',
publishes them to EventBridge, then marks them as 'sent'.
"""

from __future__ import annotations

import json

import boto3

from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point: poll proposed events, publish to EventBridge."""
    config = get_config()
    repo = get_repo()

    # Fetch proposed events
    proposed = repo.get_proposed_events(limit=50)
    if not proposed:
        return {"statusCode": 200, "dispatched": 0}

    logger.info(f"Found {len(proposed)} proposed events to dispatch")

    events_client = boto3.client("events", region_name=config.region)
    dispatched = 0

    for ev in proposed:
        try:
            entry = {
                "Source": f"cogent.{ev.source or 'unknown'}",
                "DetailType": "brain_event",
                "Detail": json.dumps({
                    "event_type": ev.event_type,
                    "source": ev.source,
                    "payload": ev.payload,
                    "parent_event_id": ev.parent_event_id,
                }),
                "EventBusName": config.event_bus_name,
            }
            events_client.put_events(Entries=[entry])
            repo.mark_event_sent(ev.id)
            dispatched += 1
            logger.info(f"Dispatched event {ev.id}: {ev.event_type}")
        except Exception:
            logger.exception(f"Failed to dispatch event {ev.id}")

    logger.info(f"Dispatched {dispatched}/{len(proposed)} events")
    return {"statusCode": 200, "dispatched": dispatched}
