from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_cascade_kill_disables_children(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, parent_process=parent_id)
    child_id = repo.upsert_process(child)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    p = repo.get_process(parent_id)
    assert p is not None
    assert p.status == ProcessStatus.DISABLED
    c = repo.get_process(child_id)
    assert c is not None
    assert c.status == ProcessStatus.DISABLED


def test_cascade_kill_recursive(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    root = Process(name="root", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    root_id = repo.upsert_process(root)
    mid = Process(name="mid", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE, parent_process=root_id)
    mid_id = repo.upsert_process(mid)
    leaf = Process(name="leaf", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, parent_process=mid_id)
    leaf_id = repo.upsert_process(leaf)

    repo.update_process_status(root_id, ProcessStatus.DISABLED)

    r = repo.get_process(root_id)
    assert r is not None
    assert r.status == ProcessStatus.DISABLED
    m = repo.get_process(mid_id)
    assert m is not None
    assert m.status == ProcessStatus.DISABLED
    l = repo.get_process(leaf_id)
    assert l is not None
    assert l.status == ProcessStatus.DISABLED


def test_cascade_kill_does_not_affect_unrelated(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, parent_process=parent_id)
    repo.upsert_process(child)
    sibling = Process(name="sibling", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    sibling_id = repo.upsert_process(sibling)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    s = repo.get_process(sibling_id)
    assert s is not None
    assert s.status == ProcessStatus.RUNNABLE


def test_already_disabled_child_not_touched(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED, parent_process=parent_id)
    child_id = repo.upsert_process(child)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    c = repo.get_process(child_id)
    assert c is not None
    assert c.status == ProcessStatus.DISABLED


# ── Task 2: Detached processes ──────────────────────────────

from cogos.capabilities.procs import ProcsCapability
from cogos.image.apply import apply_image
from cogos.image.spec import ImageSpec


def _setup_with_procs(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = ImageSpec(
        capabilities=[
            {
                "name": "procs",
                "handler": "cogos.capabilities.procs:ProcsCapability",
                "description": "",
                "instructions": "",
                "schema": None,
                "iam_role_arn": None,
                "metadata": None,
            },
        ]
    )
    apply_image(spec, repo)
    init_proc = Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    init_id = repo.upsert_process(init_proc)
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE, parent_process=init_id)
    parent_id = repo.upsert_process(parent)
    return repo, init_id, parent_id


def test_spawn_detached_sets_init_parent(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="detached-child", content="hello", detached=True)
    child = repo.get_process_by_name("detached-child")
    assert child is not None
    assert child.parent_process == init_id


def test_spawn_normal_sets_caller_parent(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="normal-child", content="hello")
    child = repo.get_process_by_name("normal-child")
    assert child is not None
    assert child.parent_process == parent_id


def test_detach_reparents_to_init(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    result = procs.spawn(name="child", content="hello")
    child = repo.get_process_by_name("child")
    assert child is not None
    assert child.parent_process == parent_id

    assert child.id is not None
    procs.detach(str(child.id))
    child = repo.get_process_by_name("child")
    assert child is not None
    assert child.parent_process == init_id


def test_cascade_kill_skips_detached(tmp_path):
    repo, init_id, parent_id = _setup_with_procs(tmp_path)
    procs = ProcsCapability(repo, parent_id)
    procs.spawn(name="attached", content="a")
    procs.spawn(name="detached", content="d", detached=True)

    repo.update_process_status(parent_id, ProcessStatus.DISABLED)

    att = repo.get_process_by_name("attached")
    assert att is not None
    assert att.status == ProcessStatus.DISABLED
    det = repo.get_process_by_name("detached")
    assert det is not None
    assert det.status == ProcessStatus.RUNNABLE


def test_init_spawn_detached_does_not_crash(tmp_path):
    """When init spawns detached children, parent_id is None.

    The handler registration for parent wakeup must be skipped (not attempted
    with process=None which violates NOT NULL).
    """
    repo = SqliteRepository(str(tmp_path))
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)
    init_proc = Process(name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    init_id = repo.upsert_process(init_proc)

    init_procs = ProcsCapability(repo, init_id)
    result = init_procs.spawn(name="cog-a", content="a", mode="daemon", detached=True)
    assert not hasattr(result, "error"), f"spawn cog-a failed: {getattr(result, 'error', '')}"

    result = init_procs.spawn(name="cog-b", content="b", mode="daemon", detached=True)
    assert not hasattr(result, "error"), f"spawn cog-b failed: {getattr(result, 'error', '')}"

    assert repo.get_process_by_name("cog-a") is not None
    assert repo.get_process_by_name("cog-b") is not None
