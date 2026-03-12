"""Tests for EventsCapability scoping: _narrow(), _check(), emit/query guards."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.events import EventsCapability


@pytest.fixture
def repo():
    mock = MagicMock()
    mock.append_event.return_value = uuid4()
    mock.get_events.return_value = []
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestUnscopedEmit:
    def test_unscoped_allows_any_emit(self, repo, pid):
        cap = EventsCapability(repo, pid)
        result = cap.emit("task:completed", {"task_id": "1"})
        assert result.event_type == "task:completed"

    def test_unscoped_allows_any_query(self, repo, pid):
        cap = EventsCapability(repo, pid)
        cap.query("task:completed")  # should not raise

    def test_unscoped_query_no_filter(self, repo, pid):
        cap = EventsCapability(repo, pid)
        cap.query()  # should not raise


class TestScopedEmit:
    def test_scoped_emit_allows_matching_pattern(self, repo, pid):
        cap = EventsCapability(repo, pid).scope(emit=["task:*"])
        result = cap.emit("task:completed", {"task_id": "1"})
        assert result.event_type == "task:completed"

    def test_scoped_emit_allows_exact_match(self, repo, pid):
        cap = EventsCapability(repo, pid).scope(emit=["task:completed"])
        result = cap.emit("task:completed")
        assert result.event_type == "task:completed"

    def test_scoped_emit_denies_non_matching(self, repo, pid):
        cap = EventsCapability(repo, pid).scope(emit=["task:*"])
        with pytest.raises(PermissionError):
            cap.emit("email:sent")

    def test_scoped_emit_multiple_patterns(self, repo, pid):
        cap = EventsCapability(repo, pid).scope(emit=["task:*", "email:*"])
        cap.emit("task:completed")
        cap.emit("email:sent")
        with pytest.raises(PermissionError):
            cap.emit("file:uploaded")


class TestScopedQuery:
    def test_scoped_query_allows_matching(self, repo, pid):
        cap = EventsCapability(repo, pid).scope(query=["task:*"])
        cap.query("task:completed")  # should not raise

    def test_scoped_query_denies_non_matching(self, repo, pid):
        cap = EventsCapability(repo, pid).scope(query=["task:*"])
        with pytest.raises(PermissionError):
            cap.query("email:sent")

    def test_scoped_query_no_filter_denied(self, repo, pid):
        """Query with no event_type filter is denied when scope restricts query."""
        cap = EventsCapability(repo, pid).scope(query=["task:*"])
        with pytest.raises(PermissionError, match="Event type required"):
            cap.query()


class TestNarrow:
    def test_narrow_intersects_emit_patterns(self, repo, pid):
        cap = EventsCapability(repo, pid)
        s1 = cap.scope(emit=["task:*", "email:*"])
        s2 = s1.scope(emit=["task:*", "file:*"])
        assert set(s2._scope["emit"]) == {"task:*"}

    def test_narrow_wildcard_existing_keeps_new(self, repo, pid):
        """If existing has '*', keep the narrower new patterns."""
        cap = EventsCapability(repo, pid)
        s1 = cap.scope(emit=["*"])
        s2 = s1.scope(emit=["task:*"])
        assert s2._scope["emit"] == ["task:*"]

    def test_narrow_wildcard_new_keeps_existing(self, repo, pid):
        """If new has '*', keep the existing (already narrower) patterns."""
        cap = EventsCapability(repo, pid)
        s1 = cap.scope(emit=["task:*"])
        s2 = s1.scope(emit=["*"])
        assert s2._scope["emit"] == ["task:*"]

    def test_narrow_only_one_side_has_key(self, repo, pid):
        cap = EventsCapability(repo, pid)
        s1 = cap.scope(emit=["task:*"])
        s2 = s1.scope(query=["email:*"])
        assert s2._scope["emit"] == ["task:*"]
        assert s2._scope["query"] == ["email:*"]

    def test_narrow_query_intersects(self, repo, pid):
        cap = EventsCapability(repo, pid)
        s1 = cap.scope(query=["task:*", "email:*"])
        s2 = s1.scope(query=["email:*"])
        assert s2._scope["query"] == ["email:*"]
