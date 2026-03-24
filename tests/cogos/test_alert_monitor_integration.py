"""Integration test: full alert pipeline from emit to monitor action."""

from datetime import datetime, timezone

from cogos.capabilities.alert_monitor import AlertMonitorCapability
from cogos.capabilities.alerts import AlertsCapability
from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    emitter = Process(name="noisy-proc", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    emitter_id = repo.upsert_process(emitter)
    monitor_proc = Process(name="alert-monitor", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    monitor_id = repo.upsert_process(monitor_proc)

    for name in ["system:alerts", "supervisor:alerts"]:
        ch = Channel(name=name, owner_process=monitor_id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)

    return repo, emitter_id, monitor_id


def _stamp_alerts(repo):
    """No-op: SqliteRepository.create_alert sets created_at automatically."""
    pass


def test_full_pipeline_spam(tmp_path):
    """Emit 10 alerts -> monitor detects spam -> suppression alert emitted."""
    repo, emitter_id, monitor_id = _setup(tmp_path)

    emitter_alerts = AlertsCapability(repo, emitter_id)
    for i in range(10):
        emitter_alerts.warning("test:noisy", f"error {i}")
    _stamp_alerts(repo)

    # Verify alerts went to channel
    ch = repo.get_channel_by_name("system:alerts")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=100)
    assert len(msgs) == 10

    # Monitor runs
    monitor_cap = AlertMonitorCapability(repo, monitor_id)
    result = monitor_cap.check()

    assert result.rules_triggered >= 1
    assert result.actions_taken >= 1

    # Stamp any new alerts created by the monitor so list_alerts can sort them
    _stamp_alerts(repo)

    # Verify suppression alert exists
    all_alerts = repo.list_alerts()
    monitor_alerts = [a for a in all_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) >= 1
    assert any(a.alert_type == "monitor:spam_detected" for a in monitor_alerts)


def test_full_pipeline_emergency(tmp_path):
    """Emit emergency alert -> monitor escalates to supervisor channel."""
    repo, emitter_id, monitor_id = _setup(tmp_path)

    # Create emergency alert directly (AlertsCapability only exposes warning/error=critical)
    repo.create_alert(
        severity="emergency",
        alert_type="system:crash",
        source="critical-proc",
        message="total failure",
    )
    _stamp_alerts(repo)

    monitor_cap = AlertMonitorCapability(repo, monitor_id)
    result = monitor_cap.check()

    assert result.actions_taken >= 1

    # Verify escalation in supervisor channel
    ch = repo.get_channel_by_name("supervisor:alerts")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) >= 1
    assert msgs[0].payload["rule"] == "monitor:critical_signal"
