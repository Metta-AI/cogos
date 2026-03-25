from cogos.capabilities.procs import ProcessError
from cogos.db.sqlite_repository import SqliteRepository
from cogos.image.apply import apply_image
from cogos.image.spec import ImageSpec


def _make_spec() -> ImageSpec:
    return ImageSpec(
        capabilities=[
            {
                "name": "dir",
                "handler": "cogos.capabilities.files.FilesCapability",
                "description": "Directory access",
                "instructions": "",
                "schema": {},
                "iam_role_arn": None,
                "metadata": {},
            },
        ],
        resources=[
            {
                "name": "lambda_slots",
                "type": "pool",
                "capacity": 5,
                "metadata": {"description": "Concurrent Lambda slots"},
            },
        ],
        processes=[
            {
                "name": "scheduler",
                "mode": "daemon",
                "content": "@{cogos/scheduler.md}",
                "runner": "lambda",
                "model": None,
                "priority": 100.0,
                "capabilities": ["dir"],
                "handlers": [],
                "metadata": {},
            },
        ],
        cron_rules=[],
        files={"cogos/scheduler.md": "You are the scheduler."},
    )


def test_apply_creates_capabilities(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    caps = repo.list_capabilities()
    assert caps is not None
    assert len(caps) == 1
    assert caps[0].name == "dir"


def test_apply_creates_files(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    f = repo.get_file_by_key("cogos/scheduler.md")
    assert f is not None
    fv = repo.get_active_file_version(f.id)
    assert fv is not None
    assert fv.content == "You are the scheduler."


def test_apply_derives_file_includes_from_inline_refs(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = ImageSpec(
        files={
            "prompts/root.md": "Root prompt\n@{docs/shared.md}",
            "docs/shared.md": "Shared context",
        }
    )

    apply_image(spec, repo)

    f = repo.get_file_by_key("prompts/root.md")
    assert f is not None
    assert f.includes == ["docs/shared.md"]


def test_apply_creates_processes_with_bindings(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    procs = repo.list_processes()
    assert procs is not None
    assert len(procs) == 1
    assert procs[0].name == "scheduler"

    handlers = repo.list_handlers(process_id=procs[0].id)
    assert handlers is not None
    assert len(handlers) == 0


def test_apply_capability_grants_have_names(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    procs = repo.list_processes()
    assert procs is not None
    pcs = repo.list_process_capabilities(procs[0].id)
    assert pcs is not None
    assert len(pcs) == 1
    assert pcs[0].name == "dir"
    assert pcs[0].config is None


def test_apply_creates_resources(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    resources = repo.list_resources()
    assert resources is not None
    assert len(resources) == 1
    assert resources[0].name == "lambda_slots"
    assert resources[0].capacity == 5.0
    assert resources[0].resource_type.value == "pool"


def test_apply_creates_cron_rules(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    rules = repo.list_cron_rules()
    assert rules is not None
    assert len(rules) == 0


def test_apply_upsert_is_idempotent(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)
    apply_image(spec, repo)

    assert len(repo.list_capabilities()) == 1
    assert len(repo.list_resources()) == 1
    assert len(repo.list_processes()) == 1
    assert len(repo.list_cron_rules()) == 0
    handlers = repo.list_handlers(process_id=repo.list_processes()[0].id)
    assert handlers is not None
    assert len(handlers) == 0


def test_spawn_with_named_scoped_capabilities(tmp_path):
    """ProcsCapability.spawn() should create named grants with scope config."""
    from uuid import UUID

    from cogos.capabilities.procs import ProcsCapability

    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
    assert parent is not None
    procs_cap = ProcsCapability(repo, parent.id)

    # Spawn with named capabilities — None means unscoped lookup by name
    result = procs_cap.spawn(
        name="child_worker",
        content="do work",
        capabilities={"dir": None},
    )
    assert not isinstance(result, ProcessError)
    assert result.name == "child_worker"
    child_proc = repo.get_process_by_name("child_worker")
    assert child_proc is not None
    assert str(child_proc.parent_process) == str(parent.id)

    # Verify the grant
    assert not isinstance(result, ProcessError)
    child = repo.get_process(UUID(result.id))
    assert child is not None
    pcs = repo.list_process_capabilities(child.id)
    assert pcs is not None
    assert len(pcs) == 1
    assert pcs[0].name == "dir"
    assert pcs[0].config is None


def test_spawn_with_scoped_config(tmp_path):
    """Spawn with a scope config dict stored on the grant."""
    from unittest.mock import MagicMock
    from uuid import UUID

    from cogos.capabilities.procs import ProcsCapability

    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
    assert parent is not None
    procs_cap = ProcsCapability(repo, parent.id)

    # Simulate a scoped capability instance by creating a mock with _scope
    scoped_files = MagicMock()
    scoped_files.__class__.__name__ = "DirCapability"
    scoped_files._scope = {"prefix": "/readonly/", "ops": ["list", "read"]}

    result = procs_cap.spawn(
        name="reader",
        content="read only",
        capabilities={"workspace": scoped_files},
    )

    assert not isinstance(result, ProcessError)
    child = repo.get_process(UUID(result.id))
    assert child is not None
    pcs = repo.list_process_capabilities(child.id)
    assert pcs is not None
    assert len(pcs) == 1
    assert pcs[0].name == "workspace"
    assert pcs[0].config == {"prefix": "/readonly/", "ops": ["list", "read"]}


def test_apply_does_not_disable_stale_processes(tmp_path):
    """Stale process cleanup is now owned by init.py, not apply_image."""
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    # Manually add a "stale" process (no parent, simulating a previous image boot)
    from cogos.db.models import Process, ProcessMode, ProcessStatus

    stale = Process(
        name="old-daemon", mode=ProcessMode.DAEMON, content="old", status=ProcessStatus.WAITING, required_tags=[]
    )
    repo.upsert_process(stale)
    _tmp_get_process_by_name = repo.get_process_by_name("old-daemon")
    assert _tmp_get_process_by_name is not None
    assert _tmp_get_process_by_name.status == ProcessStatus.WAITING

    # Re-apply the image — stale process cleanup is NOT done by apply_image
    counts = apply_image(spec, repo)
    assert "stale_disabled" not in counts
    # Process stays in its original state
    _tmp_get_process_by_name = repo.get_process_by_name("old-daemon")
    assert _tmp_get_process_by_name is not None
    assert _tmp_get_process_by_name.status == ProcessStatus.WAITING


def test_apply_preserves_spawned_children(tmp_path):
    """Spawned child processes should not be touched by apply_image."""
    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
    assert parent is not None

    from cogos.db.models import Process, ProcessMode, ProcessStatus

    child = Process(
        name="spawned-child",
        mode=ProcessMode.ONE_SHOT,
        content="work",
        status=ProcessStatus.RUNNABLE,
        required_tags=[],
        parent_process=parent.id,
    )
    repo.upsert_process(child)

    # Re-apply — spawned child should be preserved
    counts = apply_image(spec, repo)
    assert "stale_disabled" not in counts
    _tmp_get_process_by_name = repo.get_process_by_name("spawned-child")
    assert _tmp_get_process_by_name is not None
    assert _tmp_get_process_by_name.status == ProcessStatus.RUNNABLE


def test_channel_message_idempotency(tmp_path):
    """Duplicate channel messages with the same idempotency key should be ignored."""
    from cogos.db.models import Channel, ChannelMessage, ChannelType

    repo = SqliteRepository(str(tmp_path))
    ch = Channel(name="test-channel", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("test-channel")
    assert ch is not None

    # First message
    msg1 = ChannelMessage(channel=ch.id, payload={"content": "hello"}, idempotency_key="discord:123")
    id1 = repo.append_channel_message(msg1)

    # Duplicate
    msg2 = ChannelMessage(channel=ch.id, payload={"content": "hello"}, idempotency_key="discord:123")
    id2 = repo.append_channel_message(msg2)

    assert id1 == id2
    msgs = repo.list_channel_messages(ch.id)
    assert msgs is not None
    assert len(msgs) == 1


def test_channel_message_without_idempotency_key(tmp_path):
    """Messages without idempotency key should not be deduplicated."""
    from cogos.db.models import Channel, ChannelMessage, ChannelType

    repo = SqliteRepository(str(tmp_path))
    ch = Channel(name="test-channel", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("test-channel")
    assert ch is not None

    msg1 = ChannelMessage(channel=ch.id, payload={"content": "hello"})
    msg2 = ChannelMessage(channel=ch.id, payload={"content": "hello"})
    repo.append_channel_message(msg1)
    repo.append_channel_message(msg2)

    msgs = repo.list_channel_messages(ch.id)
    assert msgs is not None
    assert len(msgs) == 2


def test_spawn_multiple_grants_same_capability(tmp_path):
    """A process can have multiple named grants of the same capability."""
    from unittest.mock import MagicMock
    from uuid import UUID

    from cogos.capabilities.procs import ProcsCapability

    repo = SqliteRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
    assert parent is not None
    procs_cap = ProcsCapability(repo, parent.id)

    files_ro = MagicMock()
    files_ro.__class__.__name__ = "DirCapability"
    files_ro._scope = {"prefix": "/config/", "ops": ["read"]}

    files_rw = MagicMock()
    files_rw.__class__.__name__ = "DirCapability"
    files_rw._scope = {"prefix": "/scratch/", "ops": ["list", "read", "write"]}

    result = procs_cap.spawn(
        name="multi_files",
        content="multiple file scopes",
        capabilities={"config": files_ro, "scratch": files_rw},
    )

    assert not isinstance(result, ProcessError)
    child = repo.get_process(UUID(result.id))
    assert child is not None
    pcs = repo.list_process_capabilities(child.id)
    assert pcs is not None
    assert len(pcs) == 2
    by_name = {pc.name: pc for pc in pcs}
    assert by_name["config"].config == {"prefix": "/config/", "ops": ["read"]}
    assert by_name["scratch"].config == {"prefix": "/scratch/", "ops": ["list", "read", "write"]}
