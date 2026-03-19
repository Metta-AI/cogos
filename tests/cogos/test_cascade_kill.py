from uuid import uuid4
from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_cascade_kill_disables_children(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                    parent_process=parent_id)
    child_id = repo.upsert_process(child)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    assert repo.get_process(parent_id).status == ProcessStatus.DISABLED
    assert repo.get_process(child_id).status == ProcessStatus.DISABLED


def test_cascade_kill_recursive(tmp_path):
    repo = LocalRepository(str(tmp_path))
    root = Process(name="root", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    root_id = repo.upsert_process(root)
    mid = Process(name="mid", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE,
                  parent_process=root_id)
    mid_id = repo.upsert_process(mid)
    leaf = Process(name="leaf", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                   parent_process=mid_id)
    leaf_id = repo.upsert_process(leaf)

    repo.update_process_status(root_id, ProcessStatus.DISABLED)

    assert repo.get_process(root_id).status == ProcessStatus.DISABLED
    assert repo.get_process(mid_id).status == ProcessStatus.DISABLED
    assert repo.get_process(leaf_id).status == ProcessStatus.DISABLED


def test_cascade_kill_does_not_affect_unrelated(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                    parent_process=parent_id)
    repo.upsert_process(child)
    sibling = Process(name="sibling", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    sibling_id = repo.upsert_process(sibling)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    assert repo.get_process(sibling_id).status == ProcessStatus.RUNNABLE


def test_non_disable_does_not_cascade(tmp_path):
    repo = LocalRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE,
                    parent_process=parent_id)
    child_id = repo.upsert_process(child)

    repo.update_process_status(parent_id, ProcessStatus.COMPLETED)

    assert repo.get_process(child_id).status == ProcessStatus.RUNNABLE


# ── Task 2: Detached processes ──────────────────────────────

from cogos.capabilities.procs import ProcsCapability
from cogos.image.spec import ImageSpec
from cogos.image.apply import apply_image


def _setup_with_procs(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)
    init_proc = Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
    init_id = repo.upsert_process(init_proc)
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE,
                     parent_process=init_id)
    parent_id = repo.upsert_process(parent)
    return repo, init_id, parent_id


def test_spawn_detached_sets_init_parent(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="detached-child", content="hello", detached=True)
    child = repo.get_process_by_name("detached-child")
    assert child.parent_process == init_id


def test_spawn_normal_sets_caller_parent(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="normal-child", content="hello")
    child = repo.get_process_by_name("normal-child")
    assert child.parent_process == parent_id


def test_detach_reparents_to_init(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="child", content="hello")
    child = repo.get_process_by_name("child")
    assert child.parent_process == parent_id

    procs.detach(str(child.id))
    child = repo.get_process_by_name("child")
    assert child.parent_process == init_id


def test_cascade_kill_skips_detached(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    procs.spawn(name="attached", content="a")
    procs.spawn(name="detached", content="d", detached=True)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    assert repo.get_process_by_name("attached").status == ProcessStatus.DISABLED
    assert repo.get_process_by_name("detached").status == ProcessStatus.RUNNABLE


def test_init_spawn_detached_does_not_crash(tmp_path):
    """When init spawns detached children, parent_id is None.

    The handler registration for parent wakeup must be skipped (not attempted
    with process=None which violates NOT NULL).
    """
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)
    init_proc = Process(name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    init_id = repo.upsert_process(init_proc)

    # Spawn from init itself (detached=True, parent_id becomes None)
    init_procs = ProcsCapability(repo, init_id)
    result = init_procs.spawn(name="cog-a", content="a", mode="daemon", detached=True)
    assert not hasattr(result, "error"), f"spawn cog-a failed: {getattr(result, 'error', '')}"

    result = init_procs.spawn(name="cog-b", content="b", mode="daemon", detached=True)
    assert not hasattr(result, "error"), f"spawn cog-b failed: {getattr(result, 'error', '')}"

    # Both processes should exist
    assert repo.get_process_by_name("cog-a") is not None
    assert repo.get_process_by_name("cog-b") is not None
