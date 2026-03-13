"""Test that Process model accepts idle_timeout_ms."""
from cogos.db.models import Process, ProcessMode


def test_process_idle_timeout_default_none():
    p = Process(name="test", mode=ProcessMode.DAEMON)
    assert p.idle_timeout_ms is None


def test_process_idle_timeout_set():
    p = Process(name="test", mode=ProcessMode.DAEMON, idle_timeout_ms=300_000)
    assert p.idle_timeout_ms == 300_000
