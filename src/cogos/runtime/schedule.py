"""Shared helpers for scheduled channel messages."""

from __future__ import annotations

from datetime import datetime, timezone

from cogos.db.models import Channel, ChannelMessage, ChannelType

_FIELD_LIMITS = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),  # weekday; Sunday == 0
)


def _parse_int(value: str) -> int:
    parsed = int(value)
    return 0 if parsed == 7 else parsed


def _field_matches(expr: str, value: int, lower: int, upper: int) -> bool:
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue

        step = 1
        base = part
        if "/" in part:
            base, step_raw = part.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                raise ValueError(f"invalid cron step {step_raw!r}")

        if base == "*":
            start = lower
            end = upper
        elif "-" in base:
            start_raw, end_raw = base.split("-", 1)
            start = _parse_int(start_raw)
            end = _parse_int(end_raw)
        else:
            start = end = _parse_int(base)

        if start < lower or end > upper or start > end:
            raise ValueError(f"invalid cron range {part!r}")

        if value < start or value > end:
            continue

        if (value - start) % step == 0:
            return True

    return False


def cron_matches(expression: str, now: datetime) -> bool:
    """Return True when a five-field cron expression matches *now*."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"invalid cron expression {expression!r}")

    values = (
        now.minute,
        now.hour,
        now.day,
        now.month,
        (now.weekday() + 1) % 7,
    )

    return all(
        _field_matches(field, value, lower, upper)
        for field, value, (lower, upper) in zip(fields, values, _FIELD_LIMITS, strict=True)
    )


def _ensure_named_channel(repo, channel_name: str) -> Channel:
    channel = repo.get_channel_by_name(channel_name)
    if channel is not None:
        return channel

    repo.upsert_channel(Channel(name=channel_name, channel_type=ChannelType.NAMED))
    channel = repo.get_channel_by_name(channel_name)
    if channel is None:
        raise RuntimeError(f"failed to create scheduled channel {channel_name}")
    return channel


def emit_channel_message(repo, channel_name: str, payload: dict | None = None) -> None:
    """Append a message to a named channel, creating the channel if needed."""
    channel = _ensure_named_channel(repo, channel_name)
    repo.append_channel_message(
        ChannelMessage(
            channel=channel.id,
            sender_process=None,
            payload=payload if payload is not None else {},
        )
    )


def apply_scheduled_messages(repo, *, now: datetime | None = None) -> int:
    """Emit system tick and cron messages through the shared channel model."""
    now = now or datetime.now(timezone.utc)

    emitted = 0
    emit_channel_message(repo, "system:tick:minute")
    emitted += 1

    if now.minute == 0:
        emit_channel_message(repo, "system:tick:hour")
        emitted += 1

    for rule in repo.list_cron_rules(enabled_only=True):
        if cron_matches(rule.expression, now):
            emit_channel_message(repo, rule.channel_name, dict(rule.payload))
            emitted += 1

    return emitted
