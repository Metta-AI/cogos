"""Channel management routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.channels.schema_validator import SchemaValidationError, SchemaValidator
from cogos.db.models import Channel, ChannelMessage
from dashboard.db import get_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["channels"])


class ChannelOut(BaseModel):
    id: str
    name: str
    channel_type: str
    owner_process: str | None = None
    owner_process_name: str | None = None
    schema_name: str | None = None
    schema_id: str | None = None
    schema_definition: dict | None = None
    inline_schema: dict | None = None
    auto_close: bool = False
    closed_at: str | None = None
    message_count: int = 0
    subscriber_count: int = 0
    created_at: str | None = None


class ChannelMessageOut(BaseModel):
    id: str
    channel: str
    sender_process: str
    sender_process_name: str | None = None
    payload: dict
    created_at: str | None = None


class ChannelDetail(BaseModel):
    channel: ChannelOut
    messages: list[ChannelMessageOut]


class ChannelSendIn(BaseModel):
    payload: dict


class ChannelSendOut(BaseModel):
    id: str
    channel_id: str
    channel_name: str
    payload: dict


class ChannelsResponse(BaseModel):
    count: int
    channels: list[ChannelOut]


def _schema_definition(repo, ch: Channel) -> dict | None:
    if ch.inline_schema:
        return ch.inline_schema
    if ch.schema_id:
        schema = repo.get_schema(ch.schema_id)
        if schema:
            return schema.definition
    return None


def _schema_name(repo, ch: Channel) -> str | None:
    if ch.schema_id:
        schema = repo.get_schema(ch.schema_id)
        if schema:
            return schema.name
    return None


def _schema_registry(repo) -> dict[str, dict]:
    return {schema.name: schema.definition for schema in repo.list_schemas()}


@router.get("/channels", response_model=ChannelsResponse)
def list_channels(
    name: str,
    channel_type: str | None = Query(None),
    owner: str | None = Query(None),
) -> ChannelsResponse:
    repo = get_repo()
    owner_id = UUID(owner) if owner else None
    channels = repo.list_channels(owner_process=owner_id)
    if channel_type:
        channels = [ch for ch in channels if ch.channel_type.value == channel_type]

    processes = repo.list_processes()
    proc_names = {p.id: p.name for p in processes}

    out = []
    for ch in channels:
        msgs = repo.list_channel_messages(ch.id, limit=10000)
        handlers = repo.match_handlers_by_channel(ch.id)
        out.append(
            ChannelOut(
                id=str(ch.id),
                name=ch.name,
                channel_type=ch.channel_type.value,
                owner_process=str(ch.owner_process) if ch.owner_process else None,
                owner_process_name=proc_names.get(ch.owner_process) if ch.owner_process else None,
                schema_name=_schema_name(repo, ch),
                schema_id=str(ch.schema_id) if ch.schema_id else None,
                schema_definition=_schema_definition(repo, ch),
                inline_schema=ch.inline_schema,
                auto_close=ch.auto_close,
                closed_at=str(ch.closed_at) if ch.closed_at else None,
                message_count=len(msgs),
                subscriber_count=len(handlers),
                created_at=str(ch.created_at) if ch.created_at else None,
            )
        )

    return ChannelsResponse(count=len(out), channels=out)


@router.get("/channels/{channel_id}", response_model=ChannelDetail)
def get_channel(name: str, channel_id: str, limit: int = Query(50)) -> ChannelDetail:
    repo = get_repo()
    ch = repo.get_channel(UUID(channel_id))
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    processes = repo.list_processes()
    proc_names = {p.id: p.name for p in processes}
    handlers = repo.match_handlers_by_channel(ch.id)

    msgs = repo.list_channel_messages(ch.id, limit=limit)
    msg_out = [
        ChannelMessageOut(
            id=str(m.id),
            channel=str(m.channel),
            sender_process=str(m.sender_process),
            sender_process_name=proc_names.get(m.sender_process) if m.sender_process else None,
            payload=m.payload,
            created_at=str(m.created_at) if m.created_at else None,
        )
        for m in msgs
    ]

    ch_out = ChannelOut(
        id=str(ch.id),
        name=ch.name,
        channel_type=ch.channel_type.value,
        owner_process=str(ch.owner_process) if ch.owner_process else None,
        owner_process_name=proc_names.get(ch.owner_process) if ch.owner_process else None,
        schema_name=_schema_name(repo, ch),
        schema_id=str(ch.schema_id) if ch.schema_id else None,
        schema_definition=_schema_definition(repo, ch),
        inline_schema=ch.inline_schema,
        auto_close=ch.auto_close,
        closed_at=str(ch.closed_at) if ch.closed_at else None,
        message_count=len(repo.list_channel_messages(ch.id, limit=10000)),
        subscriber_count=len(handlers),
        created_at=str(ch.created_at) if ch.created_at else None,
    )

    return ChannelDetail(channel=ch_out, messages=msg_out)


@router.post("/channels/{channel_id}/messages", response_model=ChannelSendOut, status_code=201)
def send_channel_message(name: str, channel_id: str, body: ChannelSendIn) -> ChannelSendOut:
    repo = get_repo()
    ch = repo.get_channel(UUID(channel_id))
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    if ch.channel_type.value != "named":
        raise HTTPException(
            status_code=400,
            detail="Only named channels can receive dashboard-composed messages",
        )
    if ch.closed_at is not None:
        raise HTTPException(status_code=400, detail="Channel is closed")

    schema_definition = _schema_definition(repo, ch)
    if schema_definition:
        validator = SchemaValidator(
            schema_definition,
            schema_registry=_schema_registry(repo),
        )
        try:
            validator.validate(body.payload)
        except SchemaValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Schema validation failed: {exc}",
            ) from exc

    message = ChannelMessage(
        channel=ch.id,
        sender_process=None,
        payload=body.payload,
    )
    message_id = repo.append_channel_message(message)
    return ChannelSendOut(
        id=str(message_id),
        channel_id=str(ch.id),
        channel_name=ch.name,
        payload=body.payload,
    )
