"""Tests for ProcessHandle — send, recv, kill, status, wait, runs."""
from datetime import datetime, UTC
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.process_handle import ProcessHandle, RunInfo
from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus, Run, RunStatus


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def parent_id():
    return uuid4()


@pytest.fixture
def child_process():
    return Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)


class TestSendRecv:
    def test_send(self, repo, parent_id, child_process):
        send_ch = Channel(name=f"spawn:{parent_id}\u2192{child_process.id}",
                          owner_process=parent_id, channel_type=ChannelType.SPAWN)
        recv_ch = Channel(name=f"spawn:{child_process.id}\u2192{parent_id}",
                          owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.append_channel_message.return_value = uuid4()

        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=send_ch, recv_channel=recv_ch,
        )
        result = handle.send({"body": "task"})
        assert "id" in result
        repo.append_channel_message.assert_called_once()

    def test_send_no_channel(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        result = handle.send({"body": "task"})
        assert "error" in result

    def test_recv(self, repo, parent_id, child_process):
        send_ch = Channel(name="s", owner_process=parent_id, channel_type=ChannelType.SPAWN)
        recv_ch = Channel(name="r", owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=recv_ch.id, sender_process=child_process.id, payload={"result": "done"}),
        ]
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=send_ch, recv_channel=recv_ch,
        )
        msgs = handle.recv()
        assert len(msgs) == 1

    def test_recv_no_channel(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        assert handle.recv() == []


class TestKillAndStatus:
    def test_kill(self, repo, parent_id, child_process):
        repo.get_process.return_value = child_process
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        result = handle.kill()
        repo.update_process_status.assert_called_once_with(child_process.id, ProcessStatus.DISABLED)
        assert result["new_status"] == "disabled"

    def test_status(self, repo, parent_id, child_process):
        repo.get_process.return_value = child_process
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        assert handle.status() == "runnable"


class TestWait:
    def test_wait_suspends(self, repo, parent_id, child_process):
        from cogos.sandbox.executor import WaitSuspend
        run_id = uuid4()
        repo.get_channel_by_name.return_value = None
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None, run_id=run_id,
        )
        with pytest.raises(WaitSuspend):
            handle.wait()
        repo.create_wait_condition.assert_called_once()

    def test_wait_returns_if_child_already_exited(self, repo, parent_id, child_process):
        run_id = uuid4()
        ch = Channel(name="spawn", owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.get_channel_by_name.return_value = ch
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=ch.id, sender_process=child_process.id,
                           payload={"type": "child:exited", "exit_code": 0}),
        ]
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None, run_id=run_id,
        )
        handle.wait()  # should NOT raise
        repo.create_wait_condition.assert_not_called()

    def test_wait_any_suspends(self, repo, parent_id):
        from cogos.sandbox.executor import WaitSuspend
        run_id = uuid4()
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        repo.get_channel_by_name.return_value = None
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1,
                           send_channel=None, recv_channel=None, run_id=run_id)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2,
                           send_channel=None, recv_channel=None, run_id=run_id)
        with pytest.raises(WaitSuspend):
            ProcessHandle.wait_any([h1, h2])

    def test_wait_all_suspends(self, repo, parent_id):
        from cogos.sandbox.executor import WaitSuspend
        run_id = uuid4()
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        repo.get_channel_by_name.return_value = None
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1,
                           send_channel=None, recv_channel=None, run_id=run_id)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2,
                           send_channel=None, recv_channel=None, run_id=run_id)
        with pytest.raises(WaitSuspend):
            ProcessHandle.wait_all([h1, h2])

    def test_wait_without_run_id_raises(self, repo, parent_id, child_process):
        repo.get_channel_by_name.return_value = None
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        with pytest.raises(RuntimeError, match="requires run_id"):
            handle.wait()


class TestPythonWaitBan:
    def _make_handle(self, repo, parent_id, child_process, executor="python"):
        run_id = uuid4()
        parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, executor=executor)
        parent.id = parent_id
        repo.get_process.return_value = parent
        repo.get_channel_by_name.return_value = None
        return ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None, run_id=run_id,
        )

    def test_wait_raises_for_python(self, repo, parent_id, child_process):
        handle = self._make_handle(repo, parent_id, child_process, executor="python")
        with pytest.raises(RuntimeError, match="Python-executed processes"):
            handle.wait()

    def test_wait_any_raises_for_python(self, repo, parent_id, child_process):
        handle = self._make_handle(repo, parent_id, child_process, executor="python")
        with pytest.raises(RuntimeError, match="Python-executed processes"):
            ProcessHandle.wait_any([handle])

    def test_wait_all_raises_for_python(self, repo, parent_id, child_process):
        handle = self._make_handle(repo, parent_id, child_process, executor="python")
        with pytest.raises(RuntimeError, match="Python-executed processes"):
            ProcessHandle.wait_all([handle])

    def test_wait_ok_for_llm(self, repo, parent_id, child_process):
        from cogos.sandbox.executor import WaitSuspend
        handle = self._make_handle(repo, parent_id, child_process, executor="llm")
        with pytest.raises(WaitSuspend):
            handle.wait()


class TestRuns:
    def test_runs_returns_run_info(self, repo, parent_id, child_process):
        now = datetime.now(UTC)
        repo.list_runs.return_value = [
            Run(
                process=child_process.id,
                status=RunStatus.COMPLETED,
                duration_ms=1500,
                tokens_in=100,
                tokens_out=50,
                cost_usd=Decimal("0.001"),
                result={"answer": 42},
                created_at=now,
                completed_at=now,
            ),
            Run(
                process=child_process.id,
                status=RunStatus.FAILED,
                duration_ms=900,
                error="timeout",
                created_at=now,
            ),
        ]
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        runs = handle.runs(limit=3)

        repo.list_runs.assert_called_once_with(process_id=child_process.id, limit=3)
        assert len(runs) == 2
        assert isinstance(runs[0], RunInfo)
        assert runs[0].status == "completed"
        assert runs[0].result == {"answer": 42}
        assert runs[1].status == "failed"
        assert runs[1].error == "timeout"

    def test_runs_empty(self, repo, parent_id, child_process):
        repo.list_runs.return_value = []
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        assert handle.runs() == []
