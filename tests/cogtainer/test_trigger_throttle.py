"""Tests for trigger throttle_check on LocalCogtainerRepository."""

from __future__ import annotations

import time

from cogtainer.db.local_repository import LocalCogtainerRepository
from cogtainer.db.models import Trigger, TriggerConfig


def _repo(tmp_path) -> LocalCogtainerRepository:
    return LocalCogtainerRepository(data_dir=str(tmp_path))


def _make_trigger(max_events: int = 3, window: int = 60) -> Trigger:
    return Trigger(
        program_name="test-prog",
        event_pattern="test:event",
        config=TriggerConfig(max_events=max_events, throttle_window_seconds=window),
    )


class TestThrottleCheckBasic:
    def test_no_throttle_when_max_events_zero(self, tmp_path):
        repo = _repo(tmp_path)
        t = Trigger(program_name="p", event_pattern="e", config=TriggerConfig(max_events=0))
        repo.insert_trigger(t)
        result = repo.throttle_check(t.id, 0, 60)
        assert result.allowed is True
        assert result.state_changed is False

    def test_allows_under_limit(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=3)
        repo.insert_trigger(t)
        for _ in range(3):
            result = repo.throttle_check(t.id, 3, 60)
            assert result.allowed is True

    def test_rejects_at_limit(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=2)
        repo.insert_trigger(t)
        repo.throttle_check(t.id, 2, 60)
        repo.throttle_check(t.id, 2, 60)
        result = repo.throttle_check(t.id, 2, 60)
        assert result.allowed is False

    def test_rejected_counter_increments(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1)
        repo.insert_trigger(t)
        repo.throttle_check(t.id, 1, 60)
        repo.throttle_check(t.id, 1, 60)
        repo.throttle_check(t.id, 1, 60)
        trigger = repo.get_trigger(t.id)
        assert trigger is not None
        assert trigger.throttle_rejected == 2


class TestThrottleStateTransitions:
    def test_transition_to_throttled(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1)
        repo.insert_trigger(t)
        r1 = repo.throttle_check(t.id, 1, 60)
        assert r1.allowed is True
        assert r1.state_changed is False
        assert r1.throttle_active is False
        r2 = repo.throttle_check(t.id, 1, 60)
        assert r2.allowed is False
        assert r2.state_changed is True
        assert r2.throttle_active is True

    def test_no_state_change_when_already_throttled(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1)
        repo.insert_trigger(t)
        repo.throttle_check(t.id, 1, 60)
        repo.throttle_check(t.id, 1, 60)
        r3 = repo.throttle_check(t.id, 1, 60)
        assert r3.allowed is False
        assert r3.state_changed is False
        assert r3.throttle_active is True


class TestThrottleWindowExpiry:
    def test_window_expiry_allows_again(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=1, window=1)
        repo.insert_trigger(t)
        repo.throttle_check(t.id, 1, 1)
        r2 = repo.throttle_check(t.id, 1, 1)
        assert r2.allowed is False
        time.sleep(1.1)
        r3 = repo.throttle_check(t.id, 1, 1)
        assert r3.allowed is True
        assert r3.state_changed is True
        assert r3.throttle_active is False

    def test_old_timestamps_pruned(self, tmp_path):
        repo = _repo(tmp_path)
        t = _make_trigger(max_events=2, window=1)
        repo.insert_trigger(t)
        repo.throttle_check(t.id, 2, 1)
        repo.throttle_check(t.id, 2, 1)
        time.sleep(1.1)
        r1 = repo.throttle_check(t.id, 2, 1)
        assert r1.allowed is True
        r2 = repo.throttle_check(t.id, 2, 1)
        assert r2.allowed is True
