"""Tests for alert monitor action dispatcher."""

from datetime import datetime, timezone, timedelta

from cogos.capabilities.alerts import AlertsCapability
from cogos.capabilities.channels import ChannelsCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus
from cogos.db.models.alert import Alert, AlertSeverity
from cogos.lib.alert_rules import Action
from cogos.lib.alert_dispatcher import dispatch_actions


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    proc = Process(name="alert-monitor", status=ProcessStatus.RUNNING, runner="local")
    proc_id = repo.upsert_process(proc)

    # Create required channels
    for name in ["supervisor:alerts", "system:alerts"]:
        ch = Channel(name=name, owner_process=proc_id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)

    alerts_cap = AlertsCapability(repo, proc_id)
    channels_cap = ChannelsCapability(repo, proc_id)
    return repo, proc_id, alerts_cap, channels_cap


def test_suppress_action_emits_alert(tmp_path):
    repo, proc_id, alerts_cap, channels_cap = _setup(tmp_path)

    actions = [Action(
        kind="suppress",
        alert_type="monitor:spam_detected",
        message="10 alerts from test-proc",
        metadata={"source": "test-proc", "alert_type": "test:err", "count": 10},
    )]

    dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=[])

    db_alerts = repo.list_alerts()
    monitor_alerts = [a for a in db_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) == 1
    assert monitor_alerts[0].alert_type == "monitor:spam_detected"


def test_escalate_action_sends_to_channel(tmp_path):
    repo, proc_id, alerts_cap, channels_cap = _setup(tmp_path)

    actions = [Action(
        kind="escalate",
        alert_type="monitor:critical_signal",
        message="Emergency from test-proc",
        metadata={"source": "test-proc", "alert_id": "abc"},
    )]

    dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=[])

    ch = repo.get_channel_by_name("supervisor:alerts")
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["rule"] == "monitor:critical_signal"

    # Also emits a DB alert for dashboard visibility
    db_alerts = repo.list_alerts()
    monitor_alerts = [a for a in db_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) == 1


def test_dedup_skips_duplicate_action(tmp_path):
    repo, proc_id, alerts_cap, channels_cap = _setup(tmp_path)

    # Simulate existing monitor alert in the window
    existing = [Alert(
        severity=AlertSeverity.WARNING,
        alert_type="monitor:spam_detected",
        source="alert-monitor",
        message="already suppressed",
        metadata={"source": "test-proc", "alert_type": "test:err"},
        created_at=datetime.now(timezone.utc),
    )]

    actions = [Action(
        kind="suppress",
        alert_type="monitor:spam_detected",
        message="10 alerts from test-proc",
        metadata={"source": "test-proc", "alert_type": "test:err", "count": 10},
    )]

    dispatch_actions(actions, alerts_cap, channels_cap, existing_alerts=existing)

    db_alerts = repo.list_alerts()
    monitor_alerts = [a for a in db_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) == 0  # deduped
