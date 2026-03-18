"""End-to-end test: parent gets child:exited notification after child completes."""
from __future__ import annotations

from cogos.capabilities.procs import ProcsCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelType,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.image.apply import apply_image
from cogos.image.spec import ImageSpec
from cogos.runtime.local import run_and_complete
from cogos.executor.handler import ExecutorConfig


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    parent_id = repo.upsert_process(parent)
    parent = repo.get_process(parent_id)
    return repo, parent


def _noop_execute(process, event_data, run, config, repo, **kwargs):
    run.result = {"answer": 42}
    return run


def _failing_execute(process, event_data, run, config, repo, **kwargs):
    raise RuntimeError("child exploded")


def test_success_notification(tmp_path):
    repo, parent = _setup(tmp_path)
    procs = ProcsCapability(repo, parent.id)

    handle = procs.spawn(name="child-ok", content="x", executor="python", capabilities={})
    child = repo.get_process_by_name("child-ok")
    run = Run(process=child.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    config = ExecutorConfig()
    run_and_complete(child, {}, run, config, repo, execute_fn=_noop_execute)

    # Parent should have a child:exited message on the recv channel
    recv_ch_name = f"spawn:{child.id}\u2192{parent.id}"
    recv_ch = repo.get_channel_by_name(recv_ch_name)
    assert recv_ch is not None

    msgs = repo.list_channel_messages(recv_ch.id, limit=10)
    assert len(msgs) == 1
    payload = msgs[0].payload
    assert payload["type"] == "child:exited"
    assert payload["exit_code"] == 0
    assert payload["process_name"] == "child-ok"
    assert payload["error"] is None
    assert payload["result"] == {"answer": 42}


def test_failure_notification(tmp_path):
    repo, parent = _setup(tmp_path)
    procs = ProcsCapability(repo, parent.id)

    handle = procs.spawn(name="child-fail", content="x", executor="python", capabilities={})
    child = repo.get_process_by_name("child-fail")
    run = Run(process=child.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    config = ExecutorConfig()
    run_and_complete(child, {}, run, config, repo, execute_fn=_failing_execute)

    recv_ch_name = f"spawn:{child.id}\u2192{parent.id}"
    recv_ch = repo.get_channel_by_name(recv_ch_name)
    msgs = repo.list_channel_messages(recv_ch.id, limit=10)
    assert len(msgs) == 1
    payload = msgs[0].payload
    assert payload["type"] == "child:exited"
    assert payload["exit_code"] == 1
    assert payload["error"] == "child exploded"
    assert payload["result"] is None


def test_parent_handler_creates_delivery(tmp_path):
    """The parent Handler on the recv channel means match_messages creates a delivery."""
    from cogos.capabilities.scheduler import SchedulerCapability
    from uuid import UUID

    repo, parent = _setup(tmp_path)
    procs = ProcsCapability(repo, parent.id)

    handle = procs.spawn(name="child-delivery", content="x", executor="python", capabilities={})
    child = repo.get_process_by_name("child-delivery")
    run = Run(process=child.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    config = ExecutorConfig()
    run_and_complete(child, {}, run, config, repo, execute_fn=_noop_execute)

    # Run match_messages to create deliveries from the exit notification
    scheduler = SchedulerCapability(repo, process_id=UUID("00000000-0000-0000-0000-000000000000"))
    scheduler.match_messages()

    # Parent should now have a pending delivery
    assert repo.has_pending_deliveries(parent.id)


def test_handle_runs_after_completion(tmp_path):
    repo, parent = _setup(tmp_path)
    procs_cap = ProcsCapability(repo, parent.id)

    handle = procs_cap.spawn(name="child-runs", content="x", executor="python", capabilities={})
    child = repo.get_process_by_name("child-runs")
    run = Run(process=child.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    config = ExecutorConfig()
    run_and_complete(child, {}, run, config, repo, execute_fn=_noop_execute)

    # Get handle and check runs()
    h = procs_cap.get(name="child-runs")
    runs = h.runs(limit=5)
    assert len(runs) == 1
    assert runs[0].status == "completed"
