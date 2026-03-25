"""Chat routes — dashboard-to-cogent messaging via Discord channel pipeline."""

from __future__ import annotations

import logging
import os
import time
from uuid import uuid4

from fastapi import APIRouter, Query
from pydantic import BaseModel

from cogos.db.models import ChannelMessage
from cogos.db.models.channel import Channel, ChannelType
from dashboard.db import get_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _cogent_name(url_name: str) -> str:
    return os.environ.get("COGENT") or url_name


def _resolve_channel(repo, scoped: str, unscoped: str) -> Channel | None:
    ch = repo.get_channel_by_name(scoped)
    if ch is None:
        ch = repo.get_channel_by_name(unscoped)
    return ch


def _ensure_dm_channel(repo, cogent_name: str) -> Channel | None:
    for name in [f"io:discord:{cogent_name}:dm", "io:discord:dm"]:
        ch = repo.get_channel_by_name(name)
        if ch is not None:
            return ch
    scoped_name = f"io:discord:{cogent_name}:dm" if cogent_name else "io:discord:dm"
    ch = Channel(name=scoped_name, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    return repo.get_channel_by_name(scoped_name)


class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: str
    source: str
    content: str
    author: str | None = None
    timestamp: float
    type: str = "message"
    trace_id: str | None = None
    run_id: str | None = None


class ChatSendResult(BaseModel):
    ok: bool
    message_id: str


@router.post("/chat", response_model=ChatSendResult, status_code=201)
def send_chat_message(name: str, body: ChatMessageIn) -> ChatSendResult:
    repo = get_repo()
    cogent_name = _cogent_name(name)
    ch = _ensure_dm_channel(repo, cogent_name)
    if ch is None:
        return ChatSendResult(ok=False, message_id="")

    message_id = str(uuid4())
    payload = {
        "content": body.content,
        "author": "dashboard-user",
        "author_id": "dashboard",
        "channel_id": "dashboard",
        "channel_name": "dashboard",
        "message_id": message_id,
        "is_dm": True,
        "source": "dashboard",
        "timestamp": str(int(time.time() * 1000)),
    }

    msg = ChannelMessage(channel=ch.id, payload=payload)
    repo.append_channel_message(msg)
    return ChatSendResult(ok=True, message_id=message_id)


@router.get("/chat/messages", response_model=list[ChatMessageOut])
def get_chat_messages(
    name: str,
    limit: int = Query(50, ge=1, le=200),
    after: float = Query(0),
) -> list[ChatMessageOut]:
    repo = get_repo()
    cogent_name = _cogent_name(name)

    messages: list[ChatMessageOut] = []

    # Fetch more raw messages than the output limit since we filter by source
    # and the channels contain non-dashboard messages too.
    fetch_limit = max(limit * 10, 500)

    dm_ch = _resolve_channel(
        repo, f"io:discord:{cogent_name}:dm", "io:discord:dm",
    )
    if dm_ch:
        for msg in repo.list_channel_messages(dm_ch.id, limit=fetch_limit):
            p = msg.payload
            if p.get("source") != "dashboard":
                continue
            ts_raw = p.get("timestamp")
            ts = float(ts_raw) / 1000 if ts_raw else (
                msg.created_at.timestamp() if msg.created_at else 0
            )
            if ts <= after:
                continue
            messages.append(ChatMessageOut(
                id=str(msg.id),
                source="user",
                content=p.get("content", ""),
                author=p.get("author"),
                timestamp=ts,
            ))

    replies_ch = _resolve_channel(
        repo, f"io:discord:{cogent_name}:replies", "io:discord:replies",
    )
    if replies_ch:
        for msg in repo.list_channel_messages(replies_ch.id, limit=fetch_limit):
            p = msg.payload
            content = p.get("content", "")
            if not content:
                continue
            ts_raw = (
                p.get("_meta", {}).get("queued_at_ms") or p.get("timestamp")
            )
            ts = float(ts_raw) / 1000 if ts_raw else (
                msg.created_at.timestamp() if msg.created_at else 0
            )
            if ts <= after:
                continue
            msg_type = p.get("type", "message")
            meta = p.get("_meta", {})
            messages.append(ChatMessageOut(
                id=str(msg.id),
                source="cogent",
                content=content,
                author=cogent_name,
                timestamp=ts,
                type=msg_type,
                trace_id=meta.get("trace_id"),
                run_id=meta.get("run_id"),
            ))

    messages.sort(key=lambda m: m.timestamp)
    return messages[-limit:]
