"""Tests for SqliteRepository executor and executor token CRUD."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cogos.db.models import (
    Executor,
    ExecutorStatus,
    ExecutorToken,
)
from cogos.db.sqlite_repository import SqliteRepository


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(str(tmp_path))


class TestExecutorCRUD:
    def test_register_and_get(self, repo):
        e = Executor(executor_id="executor-test-abc123", executor_tags=["claude-code", "git"])
        eid = repo.register_executor(e)
        got = repo.get_executor("executor-test-abc123")
        assert got is not None
        assert got.id == eid
        assert got.executor_id == "executor-test-abc123"
        assert got.status == ExecutorStatus.IDLE
        assert got.executor_tags == ["claude-code", "git"]
        assert got.last_heartbeat_at is not None

    def test_get_nonexistent(self, repo):
        assert repo.get_executor("no-such-executor") is None

    def test_get_by_uuid(self, repo):
        e = Executor(executor_id="executor-uuid-test")
        eid = repo.register_executor(e)
        got = repo.get_executor_by_id(eid)
        assert got is not None
        assert got.executor_id == "executor-uuid-test"

    def test_reregister_updates(self, repo):
        e1 = Executor(executor_id="executor-rereg", executor_tags=["git"])
        id1 = repo.register_executor(e1)
        e2 = Executor(executor_id="executor-rereg", executor_tags=["git", "gpu"])
        id2 = repo.register_executor(e2)
        assert id1 == id2
        got = repo.get_executor("executor-rereg")
        assert got.executor_tags == ["git", "gpu"]
        assert got.status == ExecutorStatus.IDLE

    def test_list_all(self, repo):
        repo.register_executor(Executor(executor_id="exec-a"))
        repo.register_executor(Executor(executor_id="exec-b"))
        repo.register_executor(Executor(executor_id="exec-c"))
        assert len(repo.list_executors()) == 3

    def test_list_by_status(self, repo):
        repo.register_executor(Executor(executor_id="exec-idle"))
        repo.register_executor(Executor(executor_id="exec-busy"))
        repo.update_executor_status("exec-busy", ExecutorStatus.BUSY)
        idle = repo.list_executors(status=ExecutorStatus.IDLE)
        busy = repo.list_executors(status=ExecutorStatus.BUSY)
        assert len(idle) == 1
        assert idle[0].executor_id == "exec-idle"
        assert len(busy) == 1
        assert busy[0].executor_id == "exec-busy"

    def test_delete(self, repo):
        repo.register_executor(Executor(executor_id="exec-del"))
        repo.delete_executor("exec-del")
        assert repo.get_executor("exec-del") is None
        assert len(repo.list_executors()) == 0

    def test_delete_nonexistent_noop(self, repo):
        repo.delete_executor("no-such")  # should not raise


class TestExecutorSelection:
    def test_select_idle(self, repo):
        repo.register_executor(Executor(executor_id="exec-1", executor_tags=["claude-code"]))
        selected = repo.select_executor()
        assert selected is not None
        assert selected.executor_id == "exec-1"

    def test_select_none_when_all_busy(self, repo):
        repo.register_executor(Executor(executor_id="exec-1"))
        repo.update_executor_status("exec-1", ExecutorStatus.BUSY)
        assert repo.select_executor() is None

    def test_select_with_required_caps(self, repo):
        repo.register_executor(Executor(executor_id="exec-cpu", executor_tags=["claude-code", "git"]))
        repo.register_executor(Executor(executor_id="exec-gpu", executor_tags=["claude-code", "git", "gpu"]))

        # Require GPU
        selected = repo.select_executor(required_tags=["gpu"])
        assert selected is not None
        assert selected.executor_id == "exec-gpu"

        # Require only basic caps — either could match
        selected = repo.select_executor(required_tags=["claude-code", "git"])
        assert selected is not None

    def test_select_with_required_caps_no_match(self, repo):
        repo.register_executor(Executor(executor_id="exec-cpu", executor_tags=["claude-code"]))
        selected = repo.select_executor(required_tags=["gpu"])
        assert selected is None

    def test_select_prefers_caps(self, repo):
        repo.register_executor(Executor(executor_id="exec-basic", executor_tags=["claude-code"]))
        repo.register_executor(Executor(executor_id="exec-fancy", executor_tags=["claude-code", "gpu"]))
        selected = repo.select_executor(preferred_tags=["gpu"])
        assert selected.executor_id == "exec-fancy"

    def test_select_empty_repo(self, repo):
        assert repo.select_executor() is None


class TestExecutorHeartbeat:
    def test_heartbeat_updates_time(self, repo):
        repo.register_executor(Executor(executor_id="exec-hb"))
        initial = repo.get_executor("exec-hb").last_heartbeat_at
        result = repo.heartbeat_executor("exec-hb")
        assert result is True
        updated = repo.get_executor("exec-hb").last_heartbeat_at
        assert updated >= initial

    def test_heartbeat_updates_status(self, repo):
        repo.register_executor(Executor(executor_id="exec-hb"))
        run_id = uuid4()
        repo.heartbeat_executor("exec-hb", status=ExecutorStatus.BUSY, current_run_id=run_id)
        got = repo.get_executor("exec-hb")
        assert got.status == ExecutorStatus.BUSY
        assert got.current_run_id == run_id

    def test_heartbeat_nonexistent_returns_false(self, repo):
        assert repo.heartbeat_executor("no-such") is False

    def test_heartbeat_with_resource_usage(self, repo):
        repo.register_executor(Executor(executor_id="exec-hb"))
        repo.heartbeat_executor("exec-hb", resource_usage={"memory_mb": 2048, "cpu_percent": 45})
        got = repo.get_executor("exec-hb")
        assert got.metadata["resource_usage"]["memory_mb"] == 2048


class TestExecutorReaping:
    def test_reap_marks_dead(self, repo):
        repo.register_executor(Executor(executor_id="exec-old"))
        # Set last_heartbeat far in the past via direct DB update
        old_time = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
        repo._conn.execute(
            "UPDATE cogos_executor SET last_heartbeat_at = ? WHERE executor_id = ?",
            (old_time, "exec-old"),
        )
        repo._conn.commit()
        dead_count = repo.reap_stale_executors(heartbeat_interval_s=30)
        assert dead_count == 1
        got = repo.get_executor("exec-old")
        assert got.status == ExecutorStatus.DEAD

    def test_reap_marks_stale(self, repo):
        repo.register_executor(Executor(executor_id="exec-slow"))
        # Stale threshold = 3 * 30 = 90s
        stale_time = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
        repo._conn.execute(
            "UPDATE cogos_executor SET last_heartbeat_at = ? WHERE executor_id = ?",
            (stale_time, "exec-slow"),
        )
        repo._conn.commit()
        repo.reap_stale_executors(heartbeat_interval_s=30)
        got = repo.get_executor("exec-slow")
        assert got.status == ExecutorStatus.STALE

    def test_reap_skips_healthy(self, repo):
        repo.register_executor(Executor(executor_id="exec-fresh"))
        dead_count = repo.reap_stale_executors(heartbeat_interval_s=30)
        assert dead_count == 0
        got = repo.get_executor("exec-fresh")
        assert got.status == ExecutorStatus.IDLE


class TestExecutorTokenCRUD:
    def test_create_and_lookup(self, repo):
        token_hash = hashlib.sha256(b"test-secret").hexdigest()
        t = ExecutorToken(name="test-token", token_hash=token_hash)
        tid = repo.create_executor_token(t)
        got = repo.get_executor_token_by_hash(token_hash)
        assert got is not None
        assert got.id == tid
        assert got.name == "test-token"

    def test_lookup_nonexistent(self, repo):
        assert repo.get_executor_token_by_hash("nonexistent") is None

    def test_list_tokens(self, repo):
        repo.create_executor_token(ExecutorToken(name="t1", token_hash="hash1"))
        repo.create_executor_token(ExecutorToken(name="t2", token_hash="hash2"))
        tokens = repo.list_executor_tokens()
        assert len(tokens) == 2

    def test_revoke(self, repo):
        token_hash = hashlib.sha256(b"revokable").hexdigest()
        repo.create_executor_token(ExecutorToken(name="revokable", token_hash=token_hash))
        assert repo.revoke_executor_token("revokable") is True
        # Revoked token should not be found
        assert repo.get_executor_token_by_hash(token_hash) is None
        # But still in list
        tokens = repo.list_executor_tokens()
        assert len(tokens) == 1
        assert tokens[0].revoked_at is not None

    def test_revoke_nonexistent(self, repo):
        assert repo.revoke_executor_token("no-such") is False

    def test_revoke_idempotent(self, repo):
        repo.create_executor_token(ExecutorToken(name="once", token_hash="hash"))
        assert repo.revoke_executor_token("once") is True
        assert repo.revoke_executor_token("once") is False
