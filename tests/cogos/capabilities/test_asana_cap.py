"""Tests for AsanaCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.asana_cap import (
    AsanaCapability,
    AsanaError,
    CommentResult,
    TaskResult,
    TaskSummary,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScoping:
    def test_unscoped_allows_all(self, repo, pid):
        cap = AsanaCapability(repo, pid)
        cap._check("create_task")

    def test_scoped_ops_denies(self, repo, pid):
        cap = AsanaCapability(repo, pid).scope(ops=["list_tasks"])
        with pytest.raises(PermissionError):
            cap._check("create_task")

    def test_scoped_projects_denies(self, repo, pid):
        cap = AsanaCapability(repo, pid).scope(projects=["proj-1"])
        with pytest.raises(PermissionError):
            cap._check("create_task", project="proj-other")

    def test_narrow_intersects_ops(self, repo, pid):
        cap = AsanaCapability(repo, pid)
        s1 = cap.scope(ops=["create_task", "list_tasks", "update_task"])
        s2 = s1.scope(ops=["list_tasks", "add_comment"])
        assert s2._scope["ops"] == ["list_tasks"]

    def test_narrow_intersects_projects(self, repo, pid):
        cap = AsanaCapability(repo, pid)
        s1 = cap.scope(projects=["p1", "p2"])
        s2 = s1.scope(projects=["p2", "p3"])
        assert s2._scope["projects"] == ["p2"]


class TestCreateTask:
    @patch("cogos.capabilities.asana_cap.fetch_secret", return_value="test-pat")
    def test_create_task_success(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        mock_task = {
            "gid": "12345",
            "name": "Review candidate",
            "permalink_url": "https://app.asana.com/0/12345",
        }
        with patch("cogos.capabilities.asana_cap.asana") as mock_asana:
            mock_client = MagicMock()
            mock_client.tasks.create_task.return_value = mock_task
            mock_asana.Client.access_token.return_value = mock_client

            result = cap.create_task("proj-1", "Review candidate", notes="Good fit")
            assert isinstance(result, TaskResult)
            assert result.id == "12345"
            assert result.name == "Review candidate"

    @patch("cogos.capabilities.asana_cap.fetch_secret", side_effect=RuntimeError("no key"))
    def test_create_task_missing_key(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        result = cap.create_task("proj-1", "Test")
        assert isinstance(result, AsanaError)


class TestListTasks:
    @patch("cogos.capabilities.asana_cap.fetch_secret", return_value="test-pat")
    def test_list_tasks_success(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        mock_tasks = [
            {"gid": "1", "name": "Task 1", "completed": False, "assignee": {"name": "Alice"}, "due_on": "2026-03-15"},
            {"gid": "2", "name": "Task 2", "completed": True, "assignee": None, "due_on": None},
        ]
        with patch("cogos.capabilities.asana_cap.asana") as mock_asana:
            mock_client = MagicMock()
            mock_client.tasks.get_tasks.return_value = mock_tasks
            mock_asana.Client.access_token.return_value = mock_client

            results = cap.list_tasks("proj-1")
            assert len(results) == 2
            assert isinstance(results[0], TaskSummary)
            assert results[0].name == "Task 1"
            assert results[1].completed is True


class TestAddComment:
    @patch("cogos.capabilities.asana_cap.fetch_secret", return_value="test-pat")
    def test_add_comment_success(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        mock_story = {"gid": "story-1"}
        with patch("cogos.capabilities.asana_cap.asana") as mock_asana:
            mock_client = MagicMock()
            mock_client.stories.create_story_for_task.return_value = mock_story
            mock_asana.Client.access_token.return_value = mock_client

            result = cap.add_comment("task-1", "Looks good")
            assert isinstance(result, CommentResult)
            assert result.id == "story-1"
