"""Discord handler pre-processor: enriches event payload with conversation history.

Fetches recent messages from DB channels instead of routing through the bridge's
API request/response polling loop. This eliminates 2-5s of latency per message.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def enrich_discord_payload(repo, payload: dict[str, Any]) -> dict[str, Any]:
    """Add formatted conversation history to a Discord message payload.

    Reads inbound messages from the fine-grained per-source channel and
    outbound replies from the replies channel, merges and sorts them
    chronologically, then injects the formatted history as ``_history``.

    Returns the (possibly mutated) payload dict.
    """
    if not payload or not payload.get("channel_id"):
        return payload

    cogent_name = os.environ.get("COGENT", "")
    if not cogent_name:
        return payload

    channel_id = payload["channel_id"]
    is_dm = payload.get("is_dm", False)
    author_id = payload.get("author_id", "")

    try:
        history = _fetch_history(repo, cogent_name, channel_id, is_dm, author_id)
        if history:
            payload["_history"] = history
    except Exception:
        logger.debug("Failed to enrich Discord payload with history", exc_info=True)

    return payload


def _fetch_history(
    repo,
    cogent_name: str,
    channel_id: str,
    is_dm: bool,
    author_id: str,
    limit: int = 50,
) -> str:
    """Fetch and format conversation history from DB channels."""
    messages: list[tuple[Any, dict]] = []  # (created_at, formatted_entry)

    # 1. Inbound messages from the type-specific channel
    inbound_channel_name = _inbound_channel_name(cogent_name, channel_id, is_dm, author_id)
    if inbound_channel_name:
        ch = repo.get_channel_by_name(inbound_channel_name)
        if ch:
            for msg in repo.list_channel_messages(ch.id, limit=limit):
                p = msg.payload or {}
                if not p.get("content") and not p.get("attachments"):
                    continue
                messages.append((msg.created_at, _format_inbound(p)))

    # 2. Outbound replies from the replies channel
    replies_ch = repo.get_channel_by_name(f"io:discord:{cogent_name}:replies")
    if replies_ch:
        for msg in repo.list_channel_messages(replies_ch.id, limit=limit * 2):
            p = msg.payload or {}
            # Match by Discord channel ID
            if p.get("channel") != channel_id:
                continue
            # Skip reactions and non-message types
            if p.get("type") in ("reaction",):
                continue
            content = p.get("content", "")
            if not content:
                continue
            messages.append((msg.created_at, _format_outbound(p, cogent_name)))

    if not messages:
        return ""

    # Sort by timestamp and take the most recent ones
    messages.sort(key=lambda x: x[0] if x[0] else "")
    recent = messages[-limit:]
    return "\n".join(entry for _, entry in recent)


def _inbound_channel_name(cogent_name: str, channel_id: str, is_dm: bool, author_id: str) -> str | None:
    """Determine the fine-grained channel name for inbound messages."""
    if is_dm and author_id:
        return f"io:discord:{cogent_name}:dm:{author_id}"
    if not is_dm and channel_id:
        return f"io:discord:{cogent_name}:message:{channel_id}"
    return None


def _format_inbound(payload: dict) -> str:
    """Format an inbound Discord message for history context."""
    author = payload.get("author", "?")
    content = payload.get("content", "")
    message_id = payload.get("message_id", "?")
    ref = payload.get("reference_message_id")
    prefix = f"[reply to {ref}] " if ref else ""
    attachments = payload.get("attachments", [])
    att_suffix = ""
    if attachments:
        names = [a.get("filename", "file") for a in attachments if isinstance(a, dict)]
        if names:
            att_suffix = f" [attachments: {', '.join(names)}]"
    return f"[{message_id}] {prefix}{author}: {content}{att_suffix}"


def _format_outbound(payload: dict, cogent_name: str) -> str:
    """Format an outbound bot reply for history context."""
    content = payload.get("content", "")
    reply_to = payload.get("reply_to")
    prefix = f"[reply to {reply_to}] " if reply_to else ""
    files = payload.get("files", [])
    att_suffix = ""
    if files:
        names = [f.get("filename", "file") for f in files if isinstance(f, dict)]
        if names:
            att_suffix = f" [attachments: {', '.join(names)}]"
    return f"[bot] {prefix}{cogent_name}: {content}{att_suffix}"
