"""Tests for system channels registry."""

from cogos.db.models import Process, ProcessStatus
from cogos.db.sqlite_repository import SqliteRepository
from cogos.lib.channels import SYSTEM_CHANNELS, ensure_system_channels


def _repo(tmp_path) -> SqliteRepository:
    return SqliteRepository(str(tmp_path))


def test_ensure_system_channels_creates_all(tmp_path):
    """All channels in SYSTEM_CHANNELS are created."""
    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    for ch_def in SYSTEM_CHANNELS:
        ch = repo.get_channel_by_name(ch_def["name"])
        assert ch is not None, f"Channel {ch_def['name']} not created"


def test_ensure_system_channels_idempotent(tmp_path):
    """Calling twice doesn't error or duplicate."""
    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)
    ensure_system_channels(repo, init_id)

    for ch_def in SYSTEM_CHANNELS:
        ch = repo.get_channel_by_name(ch_def["name"])
        assert ch is not None


def test_system_alerts_channel_has_schema(tmp_path):
    """system:alerts channel has an inline schema."""
    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    ch = repo.get_channel_by_name("system:alerts")
    assert ch is not None
    assert ch.inline_schema is not None
    assert "fields" in ch.inline_schema
