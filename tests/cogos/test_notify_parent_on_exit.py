"""Tests for _notify_parent_on_exit in executor handler."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.executor.handler import _notify_parent_on_exit


def test_sends_exit_message_on_success():
    parent_id = uuid4()
    child_id = uuid4()
    run_id = uuid4()

    process = Process(
        id=child_id, name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(id=run_id, process=child_id, status=RunStatus.COMPLETED, result={"answer": 42})

    ch = Channel(name=f"spawn:{child_id}\u2192{parent_id}", channel_type=ChannelType.SPAWN)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = ch

    _notify_parent_on_exit(repo, process, run, exit_code=0, duration_ms=1500)

    repo.get_channel_by_name.assert_called_once_with(f"spawn:{child_id}\u2192{parent_id}")
    repo.append_channel_message.assert_called_once()
    msg = repo.append_channel_message.call_args.args[0]
    assert msg.channel == ch.id
    assert msg.payload["type"] == "child:exited"
    assert msg.payload["exit_code"] == 0
    assert msg.payload["process_name"] == "child"
    assert msg.payload["error"] is None
    assert msg.payload["result"] == {"answer": 42}
    assert msg.payload["duration_ms"] == 1500


def test_sends_exit_message_on_failure():
    parent_id = uuid4()
    child_id = uuid4()
    run_id = uuid4()

    process = Process(
        id=child_id, name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(id=run_id, process=child_id, status=RunStatus.FAILED)

    ch = Channel(name=f"spawn:{child_id}\u2192{parent_id}", channel_type=ChannelType.SPAWN)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = ch

    _notify_parent_on_exit(repo, process, run, exit_code=1, duration_ms=900, error="something broke")

    msg = repo.append_channel_message.call_args.args[0]
    assert msg.payload["type"] == "child:exited"
    assert msg.payload["exit_code"] == 1
    assert msg.payload["error"] == "something broke"
    assert msg.payload["result"] is None


def test_sends_exit_message_on_throttle():
    parent_id = uuid4()
    child_id = uuid4()

    process = Process(
        id=child_id, name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(process=child_id, status=RunStatus.THROTTLED)

    ch = Channel(name=f"spawn:{child_id}\u2192{parent_id}", channel_type=ChannelType.SPAWN)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = ch

    _notify_parent_on_exit(repo, process, run, exit_code=3, duration_ms=100, error="rate limited")

    msg = repo.append_channel_message.call_args.args[0]
    assert msg.payload["exit_code"] == 3


def test_no_parent_is_noop():
    process = Process(
        name="orphan", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=None,
    )
    run = Run(process=process.id, status=RunStatus.COMPLETED)
    repo = MagicMock()

    _notify_parent_on_exit(repo, process, run, exit_code=0, duration_ms=100)

    repo.get_channel_by_name.assert_not_called()


def test_no_channel_found_is_noop():
    parent_id = uuid4()
    process = Process(
        name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(process=process.id, status=RunStatus.COMPLETED)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = None

    _notify_parent_on_exit(repo, process, run, exit_code=0, duration_ms=100)

    repo.append_channel_message.assert_not_called()


def test_error_truncated_to_1000_chars():
    parent_id = uuid4()
    child_id = uuid4()
    process = Process(
        id=child_id, name="child", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.COMPLETED, parent_process=parent_id,
    )
    run = Run(process=child_id, status=RunStatus.FAILED)
    ch = Channel(name=f"spawn:{child_id}\u2192{parent_id}", channel_type=ChannelType.SPAWN)
    repo = MagicMock()
    repo.get_channel_by_name.return_value = ch

    long_error = "x" * 2000
    _notify_parent_on_exit(repo, process, run, exit_code=1, duration_ms=100, error=long_error)

    msg = repo.append_channel_message.call_args.args[0]
    assert len(msg.payload["error"]) == 1000
