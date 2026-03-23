import tempfile
from uuid import uuid4

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel, ChannelMessage, ChannelType, Handler, Process, ProcessMode, ProcessStatus,
    Run, RunStatus,
)
from cogos.db.models.wait_condition import WaitCondition, WaitConditionType, WaitConditionStatus


def _fresh_repo() -> LocalRepository:
    return LocalRepository(data_dir=tempfile.mkdtemp())


def _setup_parent_child(repo, *, num_children=1, with_handlers=False):
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(parent)
    run = Run(process=parent.id, status=RunStatus.SUSPENDED)
    repo.create_run(run)

    children = []
    for i in range(num_children):
        child = Process(name=f"child-{i}", mode=ProcessMode.ONE_SHOT,
                        status=ProcessStatus.RUNNING, parent_process=parent.id)
        repo.upsert_process(child)

        recv_ch = Channel(
            name=f"spawn:{child.id}\u2192{parent.id}",
            owner_process=child.id,
            channel_type=ChannelType.SPAWN,
        )
        repo.upsert_channel(recv_ch)
        if with_handlers:
            repo.create_handler(Handler(process=parent.id, channel=recv_ch.id))
        children.append((child, recv_ch))

    return parent, run, children


def _get(repo: LocalRepository, pid) -> Process:
    p = repo.get_process(pid)
    assert p is not None
    return p


def test_wait_all_blocks_until_all_children_exit():
    repo = _fresh_repo()
    parent, run, children = _setup_parent_child(repo, num_children=2, with_handlers=True)
    child_a, ch_a = children[0]
    child_b, ch_b = children[1]

    wc = WaitCondition(
        run=run.id, type=WaitConditionType.WAIT_ALL,
        pending=[str(child_a.id), str(child_b.id)],
    )
    repo.create_wait_condition(wc)

    repo.append_channel_message(ChannelMessage(
        channel=ch_a.id, sender_process=child_a.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_a.id)},
    ))
    assert _get(repo, parent.id).status == ProcessStatus.WAITING

    repo.append_channel_message(ChannelMessage(
        channel=ch_b.id, sender_process=child_b.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_b.id)},
    ))
    assert _get(repo, parent.id).status == ProcessStatus.RUNNABLE
    assert repo.get_pending_wait_condition_for_process(parent.id) is None


def test_wait_any_wakes_on_first_child():
    repo = _fresh_repo()
    parent, run, children = _setup_parent_child(repo, num_children=2, with_handlers=True)
    child_a, ch_a = children[0]

    wc = WaitCondition(
        run=run.id, type=WaitConditionType.WAIT_ANY,
        pending=[str(children[0][0].id), str(children[1][0].id)],
    )
    repo.create_wait_condition(wc)

    repo.append_channel_message(ChannelMessage(
        channel=ch_a.id, sender_process=child_a.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_a.id)},
    ))
    assert _get(repo, parent.id).status == ProcessStatus.RUNNABLE


def test_no_handler_no_wake():
    """Without a handler (no wait() called), child:exited does not wake parent."""
    repo = _fresh_repo()
    parent, _run, children = _setup_parent_child(repo, num_children=1)
    child, ch = children[0]

    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=child.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child.id)},
    ))
    assert _get(repo, parent.id).status == ProcessStatus.WAITING


def test_handler_without_wait_condition_wakes():
    """With a handler but no wait condition, child:exited wakes the parent."""
    repo = _fresh_repo()
    parent, _run, children = _setup_parent_child(repo, num_children=1, with_handlers=True)
    child, ch = children[0]

    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=child.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child.id)},
    ))
    assert _get(repo, parent.id).status == ProcessStatus.RUNNABLE


def test_non_exit_message_does_not_resolve_wait():
    repo = _fresh_repo()
    parent, run, children = _setup_parent_child(repo, num_children=1, with_handlers=True)
    child, ch = children[0]

    wc = WaitCondition(
        run=run.id, type=WaitConditionType.WAIT,
        pending=[str(child.id)],
    )
    repo.create_wait_condition(wc)

    # Regular message (not child:exited) should NOT resolve the wait
    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=child.id,
        payload={"type": "data", "result": 42},
    ))
    assert _get(repo, parent.id).status == ProcessStatus.WAITING
    assert repo.get_pending_wait_condition_for_process(parent.id) is not None


def test_orphan_cleanup_on_disable():
    repo = _fresh_repo()
    parent, run, _children = _setup_parent_child(repo, num_children=1)

    wc = WaitCondition(
        run=run.id, type=WaitConditionType.WAIT_ALL,
        pending=[str(uuid4())],
    )
    repo.create_wait_condition(wc)
    assert repo.get_pending_wait_condition_for_process(parent.id) is not None

    repo.update_process_status(parent.id, ProcessStatus.DISABLED)
    assert repo.get_pending_wait_condition_for_process(parent.id) is None
