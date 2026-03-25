"""Alert monitor action dispatcher — executes suppress and escalate actions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from cogos.capabilities.alerts import AlertsCapability
from cogos.capabilities.channels import ChannelsCapability
from cogos.db.models.alert import Alert
from cogos.lib.alert_rules import Action

logger = logging.getLogger(__name__)

DEDUP_WINDOW_SECONDS = 300  # 5 minutes


def _is_duplicate(action: Action, existing_alerts: list[Alert]) -> bool:
    """Check if an equivalent monitor action was already taken in the window."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=DEDUP_WINDOW_SECONDS)
    for alert in existing_alerts:
        if alert.source != "alert-monitor":
            continue
        if alert.alert_type != action.alert_type:
            continue
        if alert.created_at and alert.created_at < cutoff:
            continue
        # Match on key metadata fields (source + alert_type of the original alert)
        assert alert.metadata is not None, "Alert.metadata must be set for dedup check"
        meta = alert.metadata
        if (
            meta.get("source") == action.metadata.get("source")
            and meta.get("alert_type") == action.metadata.get("alert_type")
        ):
            return True
        # For unacked/critical, match on alert_id
        if meta.get("alert_id") and meta.get("alert_id") == action.metadata.get("alert_id"):
            return True
    return False


def dispatch_actions(
    actions: list[Action],
    alerts_cap: AlertsCapability,
    channels_cap: ChannelsCapability,
    existing_alerts: list[Alert],
) -> int:
    """Execute actions, skipping duplicates. Returns count of actions taken."""
    taken = 0
    for action in actions:
        if _is_duplicate(action, existing_alerts):
            logger.debug("Skipping duplicate action: %s", action.alert_type)
            continue

        if action.kind == "suppress":
            alerts_cap._emit("warning", action.alert_type, action.message, action.metadata)
            taken += 1

        elif action.kind == "escalate":
            # Send to supervisor:alerts channel
            channels_cap.send("supervisor:alerts", {
                "rule": action.alert_type,
                "alert_type": action.alert_type,
                "source_process": action.metadata.get("source", "unknown"),
                "summary": action.message,
                "recommended_action": f"investigate {action.metadata.get('source', 'unknown')}",
            })
            # Also emit DB alert for dashboard visibility
            alerts_cap._emit("warning", action.alert_type, action.message, action.metadata)
            taken += 1

    return taken
