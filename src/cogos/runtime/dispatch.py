"""Shared dispatch-envelope helpers for local and remote runtimes."""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from cogos.db.protocol import CogosRepositoryInterface

logger = logging.getLogger(__name__)


def _load_message_payload(repo: CogosRepositoryInterface, message_id: str | None) -> dict[str, Any]:
    if not message_id:
        return {}
    msg = repo.get_channel_message(UUID(message_id))
    return msg.payload or {} if msg else {}


def _resolve_channel_name(repo: CogosRepositoryInterface, message_id: str | None) -> str | None:
    if not message_id:
        return None
    msg = repo.get_channel_message(UUID(message_id))
    if msg is None:
        return None
    ch = repo.get_channel(msg.channel)
    return ch.name if ch else None


def _extract_parent_span_id(repo: CogosRepositoryInterface, message_id: str | None) -> str | None:
    if not message_id:
        return None
    try:
        msg = repo.get_channel_message(UUID(message_id))
        if msg and msg.trace_meta:
            return msg.trace_meta.get("span_id")
    except Exception:
        logger.debug("Failed to extract parent_span_id for %s", message_id, exc_info=True)
    return None


def build_dispatch_event(repo: CogosRepositoryInterface, dispatch_result: Any) -> dict[str, Any]:
    """Build the executor event envelope used by both local and prod dispatch."""
    from uuid import UUID as _UUID

    event: dict[str, Any] = {
        "process_id": dispatch_result.process_id,
        "run_id": dispatch_result.run_id,
        "process_name": getattr(dispatch_result, "process_name", None),
        "message_id": dispatch_result.message_id,
        "trace_id": getattr(dispatch_result, "trace_id", None),
        "parent_span_id": _extract_parent_span_id(repo, dispatch_result.message_id),
        "source": "channel",
        "dispatched_at_ms": int(time.time() * 1000),
        "channel_name": _resolve_channel_name(repo, dispatch_result.message_id),
        "payload": _load_message_payload(repo, dispatch_result.message_id),
    }

    try:
        proc = repo.get_process(_UUID(dispatch_result.process_id))
        if proc:
            event["content"] = proc.content
    except (ValueError, AttributeError):
        pass

    return event
