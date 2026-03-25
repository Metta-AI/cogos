"""Tests for alerts -> channel pipeline."""

from cogos.capabilities.alerts import AlertError, AlertsCapability
from cogos.db.models import Channel, ChannelType, Process, ProcessStatus
from cogos.db.sqlite_repository import SqliteRepository


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    proc = Process(name="test-proc", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    proc_id = repo.upsert_process(proc)

    # Create system:alerts channel
    ch = Channel(
        name="system:alerts",
        owner_process=proc_id,
        channel_type=ChannelType.NAMED,
    )
    repo.upsert_channel(ch)

    cap = AlertsCapability(repo, proc_id)
    return repo, proc_id, cap


def test_warning_publishes_to_channel(tmp_path):
    """alerts.warning() writes to DB AND sends to system:alerts channel."""
    repo, proc_id, cap = _setup(tmp_path)

    result = cap.warning("test:noisy", "something happened")
    assert not isinstance(result, AlertError)

    assert result.severity == "warning"

    ch = repo.get_channel_by_name("system:alerts")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["alert_type"] == "test:noisy"
    assert msgs[0].payload["severity"] == "warning"
    assert msgs[0].payload["source"] == "test-proc"


def test_error_publishes_to_channel(tmp_path):
    """alerts.error() writes to DB AND sends to system:alerts channel."""
    repo, proc_id, cap = _setup(tmp_path)

    result = cap.error("executor:crash", "OOM kill")
    assert not isinstance(result, AlertError)

    assert result.severity == "critical"

    ch = repo.get_channel_by_name("system:alerts")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["alert_type"] == "executor:crash"
    assert msgs[0].payload["severity"] == "critical"


def test_alert_without_channel_still_works(tmp_path):
    """If system:alerts channel doesn't exist, alert still goes to DB."""
    repo = SqliteRepository(str(tmp_path))
    proc = Process(name="test-proc", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    proc_id = repo.upsert_process(proc)

    # No system:alerts channel created
    cap = AlertsCapability(repo, proc_id)
    result = cap.warning("test:thing", "no channel")
    assert not isinstance(result, AlertError)

    assert result.severity == "warning"
    alerts = repo.list_alerts()
    assert len(alerts) == 1
