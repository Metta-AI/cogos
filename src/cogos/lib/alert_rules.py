"""Alert monitoring detection rules.

Each rule is a pure function: takes a list of Alert objects, returns a list of Action objects.
Stateless — all context comes from the alert list passed in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cogos.db.models.alert import Alert, AlertSeverity

MONITOR_SOURCE = "alert-monitor"


@dataclass
class Action:
    kind: str           # "suppress" | "escalate"
    alert_type: str     # e.g. "monitor:spam_detected"
    message: str
    metadata: dict = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _in_window(alert: Alert, window_seconds: int) -> bool:
    if alert.created_at is None:
        return False
    return (_now() - alert.created_at).total_seconds() <= window_seconds


def detect_spam(
    alerts: list[Alert],
    window_seconds: int = 60,
    threshold: int = 10,
) -> list[Action]:
    """Rule 1: Detect repeated identical alerts (same source + alert_type)."""
    recent = [
        a for a in alerts
        if _in_window(a, window_seconds) and a.source != MONITOR_SOURCE
    ]

    groups: dict[tuple[str, str], int] = defaultdict(int)
    for a in recent:
        groups[(a.source, a.alert_type)] += 1

    actions = []
    for (source, alert_type), count in groups.items():
        if count >= threshold:
            actions.append(Action(
                kind="suppress",
                alert_type="monitor:spam_detected",
                message=f"{count} alerts of type {alert_type} from {source} in {window_seconds}s",
                metadata={"source": source, "alert_type": alert_type, "count": count},
            ))
    return actions


def detect_escalating_rate(
    alerts: list[Alert],
    window_seconds: int = 300,
    buckets: int = 5,
) -> list[Action]:
    """Rule 2: Detect accelerating failure rate per source."""
    recent = [
        a for a in alerts
        if _in_window(a, window_seconds) and a.source != MONITOR_SOURCE
    ]

    by_source: dict[str, list[Alert]] = defaultdict(list)
    for a in recent:
        by_source[a.source].append(a)

    bucket_size = window_seconds / buckets
    now = _now()
    actions = []

    for source, source_alerts in by_source.items():
        bucket_counts = [0] * buckets
        for a in source_alerts:
            if a.created_at is None:
                continue
            age = (now - a.created_at).total_seconds()
            bucket_idx = min(int(age / bucket_size), buckets - 1)
            bucket_counts[buckets - 1 - bucket_idx] += 1

        if len(bucket_counts) < 2:
            continue
        prior = bucket_counts[:-1]
        prior_avg = sum(prior) / len(prior) if prior else 0
        last = bucket_counts[-1]

        if prior_avg > 0 and last >= 2 * prior_avg:
            actions.append(Action(
                kind="escalate",
                alert_type="monitor:escalating_rate",
                message=f"Alert rate from {source} escalating: {last} in last bucket vs {prior_avg:.1f} avg",
                metadata={"source": source, "last_bucket": last, "prior_avg": prior_avg},
            ))
    return actions


def detect_critical_signal(alerts: list[Alert]) -> list[Action]:
    """Rule 3: Any emergency-severity alert gets immediately escalated."""
    actions = []
    for a in alerts:
        if a.severity == AlertSeverity.EMERGENCY and a.source != MONITOR_SOURCE:
            actions.append(Action(
                kind="escalate",
                alert_type="monitor:critical_signal",
                message=f"Emergency alert from {a.source}: {a.message}",
                metadata={
                    "source": a.source,
                    "alert_type": a.alert_type,
                    "alert_id": str(a.id),
                },
            ))
    return actions


def detect_unacked_critical(
    alerts: list[Alert],
    stale_minutes: int = 5,
) -> list[Action]:
    """Rule 4: Critical alerts unacknowledged for too long."""
    cutoff = _now() - timedelta(minutes=stale_minutes)
    actions = []
    for a in alerts:
        if (
            a.severity == AlertSeverity.CRITICAL
            and a.acknowledged_at is None
            and a.created_at is not None
            and a.created_at < cutoff
            and a.source != MONITOR_SOURCE
        ):
            actions.append(Action(
                kind="escalate",
                alert_type="monitor:unack_escalation",
                message=f"Unacknowledged critical alert from {a.source}: {a.message}",
                metadata={
                    "source": a.source,
                    "alert_id": str(a.id),
                    "age_minutes": int((_now() - a.created_at).total_seconds() / 60),
                },
            ))
    return actions


def run_all_rules(alerts: list[Alert]) -> list[Action]:
    """Run all detection rules and return combined actions."""
    actions = []
    actions.extend(detect_spam(alerts))
    actions.extend(detect_escalating_rate(alerts))
    actions.extend(detect_critical_signal(alerts))
    actions.extend(detect_unacked_critical(alerts))
    return actions
