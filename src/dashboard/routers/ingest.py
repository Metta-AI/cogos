"""Ingest routes — receive inbound emails from CloudFlare Email Worker."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cogos.db.models import Channel, ChannelMessage, ChannelType
from dashboard.db import get_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ingest"])


class EmailPayload(BaseModel):
    event_type: str = "email:received"
    source: str = "cloudflare-email-worker"
    payload: dict


CHANNEL_NAME = "io:email:inbound"


@router.post("/ingest/email")
async def ingest_email(body: EmailPayload):
    """Receive an inbound email and write it to the io:email:inbound channel."""
    payload = body.payload
    cogent_name = payload.get("cogent")
    if not cogent_name:
        raise HTTPException(status_code=400, detail="Missing cogent in payload")

    repo = get_repo()

    # Find or create the channel
    ch = repo.get_channel_by_name(CHANNEL_NAME)
    if ch is None:
        ch = Channel(name=CHANNEL_NAME, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        ch = repo.get_channel_by_name(CHANNEL_NAME)

    if ch is None:
        raise HTTPException(status_code=500, detail="Failed to create email channel")

    # Build idempotency key from email message_id
    message_id = payload.get("message_id")
    idempotency_key = f"email:{message_id}" if message_id else None

    repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        sender_process=None,
        payload=payload,
        idempotency_key=idempotency_key,
    ))

    logger.info(
        "Ingested email cogent=%s from=%s subject=%s",
        cogent_name, payload.get("from"), payload.get("subject"),
    )

    return {"ok": True, "cogent": cogent_name}
