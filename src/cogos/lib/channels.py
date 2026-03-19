"""System channels registry — centralized definitions for all CogOS system channels."""

from __future__ import annotations

from uuid import UUID

from cogos.db.models import Channel, ChannelType


SYSTEM_CHANNELS: list[dict] = [
    # Alerts pipeline
    {"name": "system:alerts", "schema": {
        "id": "string",
        "severity": "string",
        "alert_type": "string",
        "source": "string",
        "message": "string",
        "metadata": "object",
        "timestamp": "string",
    }},
    {"name": "supervisor:alerts", "schema": {
        "rule": "string",
        "alert_type": "string",
        "source_process": "string",
        "summary": "string",
        "recent_alerts": "array",
        "recommended_action": "string",
    }},
    # Scheduling
    {"name": "system:tick:minute"},
    {"name": "system:tick:hour"},
    # Supervisor
    {"name": "supervisor:help"},
    # Discord IO
    {"name": "io:discord:dm"},
    {"name": "io:discord:mention"},
    {"name": "io:discord:message"},
    {"name": "io:discord:api:request"},
    {"name": "io:discord:api:response"},
    {"name": "discord-cog:review"},
    # Web
    {"name": "io:web:request"},
    # GitHub
    {"name": "github:discover"},
    # Diagnostics
    {"name": "system:diagnostics"},
]


def ensure_system_channels(repo, owner_process_id: UUID) -> None:
    """Create all system channels if they don't exist."""
    for ch_def in SYSTEM_CHANNELS:
        inline_schema = None
        if ch_def.get("schema"):
            inline_schema = {"fields": ch_def["schema"]}

        ch = Channel(
            name=ch_def["name"],
            owner_process=owner_process_id,
            channel_type=ChannelType.NAMED,
            inline_schema=inline_schema,
        )
        repo.upsert_channel(ch)
