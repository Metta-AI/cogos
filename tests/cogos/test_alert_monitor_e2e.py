"""End-to-end test for alert monitor capability."""

from datetime import datetime, timezone

from cogos.capabilities.alert_monitor import AlertMonitorCapability
from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    proc = Process(name="alert-monitor", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    proc_id = repo.upsert_process(proc)

    for name in ["system:alerts", "supervisor:alerts"]:
        ch = Channel(name=name, owner_process=proc_id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)

    cap = AlertMonitorCapability(repo, proc_id)
    return repo, proc_id, cap


def _stamp_alerts(repo):
    """No-op: SqliteRepository.create_alert sets created_at automatically."""
    pass


def test_check_no_alerts(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)
    result = cap.check()
    assert result.rules_triggered == 0
    assert result.actions_taken == 0


def test_check_detects_spam(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)

    for _ in range(10):
        repo.create_alert(
            severity="warning",
            alert_type="test:noisy",
            source="noisy-proc",
            message="same error",
        )

    _stamp_alerts(repo)

    result = cap.check()
    assert result.rules_triggered >= 1
    assert result.actions_taken >= 1

    # Stamp any new alerts created by the monitor itself before querying
    _stamp_alerts(repo)

    all_alerts = repo.list_alerts()
    monitor_alerts = [a for a in all_alerts if a.source == "alert-monitor"]
    assert len(monitor_alerts) >= 1


def test_check_escalates_emergency(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)

    repo.create_alert(
        severity="emergency",
        alert_type="system:crash",
        source="critical-proc",
        message="total failure",
    )

    _stamp_alerts(repo)

    result = cap.check()
    assert result.rules_triggered >= 1
    assert result.actions_taken >= 1

    ch = repo.get_channel_by_name("supervisor:alerts")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) >= 1


def test_check_deduplicates(tmp_path):
    repo, proc_id, cap = _setup(tmp_path)

    for _ in range(10):
        repo.create_alert(
            severity="warning",
            alert_type="test:noisy",
            source="noisy-proc",
            message="same error",
        )

    _stamp_alerts(repo)

    result1 = cap.check()
    assert result1.actions_taken >= 1

    # Stamp monitor-created alerts before second check
    _stamp_alerts(repo)

    result2 = cap.check()
    assert result2.actions_taken == 0
