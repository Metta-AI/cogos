"""Tool handler implementations invoked by the executor sandbox.

Each handler has the signature::

    (tool_name: str, tool_input: dict, config) -> str

*config* is a :class:`brain.lambdas.shared.config.LambdaConfig` instance
providing ``cogent_name``, ``region``, ``event_bus_name``, etc.
"""

from __future__ import annotations

import json


# ── Memory ────────────────────────────────────────────────


def memory_get(tool_name: str, tool_input: dict, config) -> str:
    """Retrieve a memory value by key."""
    from brain.lambdas.shared.db import get_repo
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
    from brain.lambdas.shared.db import get_repo
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
    from brain.db.models import Event
    from brain.lambdas.shared.db import get_repo
    from brain.lambdas.shared.events import put_event

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
    repo.insert_event(event)
    put_event(event, config.event_bus_name)

    return json.dumps({
        "event_type": event_type,
        "status": "sent",
        "payload": payload,
    })


# ── Gmail ─────────────────────────────────────────────────


def gmail_check(tool_name: str, tool_input: dict, config) -> str:
    """Check Gmail inbox for messages."""
    from channels.gmail.tools import get_gmail_client

    query = tool_input.get("query", "is:unread") or "is:unread"
    max_results = tool_input.get("max_results", 10) or 10

    client = get_gmail_client(config.cogent_name, config.region)
    profile = client.get_profile()
    messages = client.list_messages(query=query, max_results=max_results)

    if not messages:
        return json.dumps({
            "email": profile.get("emailAddress"),
            "query": query,
            "count": 0,
            "messages": [],
        })

    results = []
    for stub in messages[:max_results]:
        msg = client.get_message_metadata(stub["id"])
        headers = {}
        for h in msg.get("payload", {}).get("headers", []):
            headers[h["name"].lower()] = h["value"]
        results.append({
            "id": stub["id"],
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
        })

    return json.dumps({
        "email": profile.get("emailAddress"),
        "query": query,
        "count": len(results),
        "messages": results,
    })


def gmail_send(tool_name: str, tool_input: dict, config) -> str:
    """Send an email via Gmail."""
    from channels.gmail.sender import GmailSender
    from channels.gmail.tools import get_gmail_client

    to = tool_input.get("to", "").strip()
    subject = tool_input.get("subject", "").strip()
    body = tool_input.get("body", "")

    if not to or not subject:
        return json.dumps({"error": "gmail_send requires 'to' and 'subject'"})

    client = get_gmail_client(config.cogent_name, config.region)
    sender = GmailSender(client)
    result = sender.send_email(to=to, subject=subject, body=body)

    return json.dumps({
        "sent": True,
        "message_id": result.get("id", ""),
        "to": to,
        "subject": subject,
    })
