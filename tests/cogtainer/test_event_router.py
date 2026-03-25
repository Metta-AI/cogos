"""Tests for EventRouter — runtime-agnostic event matching."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogtainer.event_router import EventRouter, match_pattern

# ── match_pattern ────────────────────────────────────────────


def test_match_exact_pattern():
    assert match_pattern("discord:message", "discord:message") is True
    assert match_pattern("discord:message", "discord:reaction") is False
    assert match_pattern("email:received", "discord:message") is False


def test_match_glob_pattern():
    assert match_pattern("discord:*", "discord:message") is True
    assert match_pattern("discord:*", "discord:reaction") is True
    assert match_pattern("discord:*", "email:received") is False
    # Edge: pattern with only "*" matches everything
    assert match_pattern("*", "anything:goes") is True


# ── EventRouter.route_event ──────────────────────────────────


def _make_trigger(program_name: str, event_pattern: str, *, max_events: int = 0):
    """Build a mock trigger with the fields EventRouter reads."""
    trigger = MagicMock()
    trigger.id = uuid4()
    trigger.program_name = program_name
    trigger.event_pattern = event_pattern
    trigger.config.max_events = max_events
    trigger.config.throttle_window_seconds = 60
    return trigger


def _make_program(name: str, runner: str | None = None):
    program = MagicMock()
    program.name = name
    program.runner = runner
    return program


def test_route_event_matches_triggers():
    repo = MagicMock()
    runtime = MagicMock()

    trigger = _make_trigger("handler-a", "discord:message")
    repo.list_triggers.return_value = [trigger]
    repo.get_program.return_value = _make_program("handler-a")

    router = EventRouter(repo, runtime)
    result = router.route_event("discord:message", "some-source", {"text": "hi"})

    assert len(result) == 1
    assert result[0]["program_name"] == "handler-a"
    assert result[0]["trigger_id"] == str(trigger.id)
    assert result[0]["payload"] == {"text": "hi"}


def test_route_event_cascade_guard():
    repo = MagicMock()
    runtime = MagicMock()

    trigger = _make_trigger("handler-a", "discord:message")
    repo.list_triggers.return_value = [trigger]

    router = EventRouter(repo, runtime)
    # source == program_name -> should be filtered out
    result = router.route_event("discord:message", "handler-a", {})

    assert result == []


def test_route_event_no_match():
    repo = MagicMock()
    runtime = MagicMock()

    trigger = _make_trigger("handler-a", "email:received")
    repo.list_triggers.return_value = [trigger]

    router = EventRouter(repo, runtime)
    result = router.route_event("discord:message", "source", {})

    assert result == []


def test_route_event_throttled():
    repo = MagicMock()
    runtime = MagicMock()

    trigger = _make_trigger("handler-a", "discord:message", max_events=5)
    repo.list_triggers.return_value = [trigger]

    throttle_result = MagicMock()
    throttle_result.allowed = False
    repo.throttle_check.return_value = throttle_result

    router = EventRouter(repo, runtime)
    result = router.route_event("discord:message", "source", {})

    assert result == []
    repo.throttle_check.assert_called_once_with(trigger.id, 5, 60)


def test_route_event_program_not_found():
    repo = MagicMock()
    runtime = MagicMock()

    trigger = _make_trigger("missing-prog", "discord:message")
    repo.list_triggers.return_value = [trigger]
    repo.get_program.return_value = None

    router = EventRouter(repo, runtime)
    result = router.route_event("discord:message", "source", {})

    assert result == []
