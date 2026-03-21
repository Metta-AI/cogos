"""Tool handler implementations invoked by the executor sandbox.

Each handler has the signature::

    (tool_name: str, tool_input: dict, config) -> str

*config* is a :class:`cogtainer.lambdas.shared.config.LambdaConfig` instance
providing ``cogent_name``, ``region``, ``event_bus_name``, etc.
"""

from __future__ import annotations

import json

# ── Memory ────────────────────────────────────────────────


def memory_get(tool_name: str, tool_input: dict, config) -> str:
    """Retrieve a memory value by key."""
    from cogtainer.lambdas.shared.db import get_repo
    from memory.store import MemoryStore

    repo = get_repo()
    store = MemoryStore(repo)
    key = tool_input.get("key", "")
    if not key:
        return json.dumps({"error": "missing required parameter 'key'"})

    mem = store.get(key)
    if not mem:
        return json.dumps({"key": key, "found": False, "value": None})

    active_mv = mem.versions.get(mem.active_version)
    content = active_mv.content if active_mv else ""
    return json.dumps({"key": key, "found": True, "value": content})


def memory_put(tool_name: str, tool_input: dict, config) -> str:
    """Store a value in memory under a key."""
    from cogtainer.lambdas.shared.db import get_repo
    from memory.store import MemoryStore

    repo = get_repo()
    store = MemoryStore(repo)
    key = tool_input.get("key", "")
    value = tool_input.get("value", "")
    if not key:
        return json.dumps({"error": "missing required parameter 'key'"})

    result = store.upsert(key, value, source="cogent")
    if result is None:
        return json.dumps({"key": key, "status": "unchanged"})
    return json.dumps({"key": key, "status": "saved", "id": str(result.id)})


# ── Events ────────────────────────────────────────────────


def event_send(tool_name: str, tool_input: dict, config) -> str:
    """Send an event to the EventBridge bus."""
    from cogtainer.db.models import Event
    from cogtainer.lambdas.shared.db import get_repo
    from cogtainer.lambdas.shared.events import put_event

    event_type = tool_input.get("event_type", "")
    if not event_type:
        return json.dumps({"error": "missing required parameter 'event_type'"})

    payload = tool_input.get("payload", {})
    event = Event(
        event_type=event_type,
        source=config.cogent_name,
        payload=payload,
    )

    repo = get_repo()
    repo.append_event(event)
    put_event(event, config.event_bus_name)

    return json.dumps({
        "event_type": event_type,
        "status": "sent",
        "payload": payload,
    })
