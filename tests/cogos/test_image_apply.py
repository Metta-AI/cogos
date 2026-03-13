from cogos.db.local_repository import LocalRepository
from cogos.image.spec import ImageSpec
from cogos.image.apply import apply_image


def _make_spec() -> ImageSpec:
    return ImageSpec(
        capabilities=[
            {"name": "dir", "handler": "cogos.capabilities.files.FilesCapability",
             "description": "Directory access", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
        ],
        resources=[
            {"name": "lambda_slots", "type": "pool", "capacity": 5,
             "metadata": {"description": "Concurrent Lambda slots"}},
        ],
        processes=[
            {"name": "scheduler", "mode": "daemon", "content": "@{cogos/scheduler}",
             "runner": "lambda", "model": None,
             "priority": 100.0, "capabilities": ["dir"],
             "handlers": [], "metadata": {}},
        ],
        cron_rules=[],
        files={"cogos/scheduler": "You are the scheduler."},
    )


def test_apply_creates_capabilities(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    caps = repo.list_capabilities()
    assert len(caps) == 1
    assert caps[0].name == "dir"


def test_apply_creates_files(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    f = repo.get_file_by_key("cogos/scheduler")
    assert f is not None
    fv = repo.get_active_file_version(f.id)
    assert fv.content == "You are the scheduler."


def test_apply_creates_processes_with_bindings(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "scheduler"

    handlers = repo.list_handlers(process_id=procs[0].id)
    assert len(handlers) == 0


def test_apply_capability_grants_have_names(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    procs = repo.list_processes()
    pcs = repo.list_process_capabilities(procs[0].id)
    assert len(pcs) == 1
    assert pcs[0].name == "dir"
    assert pcs[0].config is None


def test_apply_creates_resources(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    resources = repo.list_resources()
    assert len(resources) == 1
    assert resources[0].name == "lambda_slots"
    assert resources[0].capacity == 5.0
    assert resources[0].resource_type.value == "pool"


def test_apply_creates_cron_rules(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    rules = repo.list_cron_rules()
    assert len(rules) == 0


def test_apply_upsert_is_idempotent(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)
    apply_image(spec, repo)

    assert len(repo.list_capabilities()) == 1
    assert len(repo.list_resources()) == 1
    assert len(repo.list_processes()) == 1
    assert len(repo.list_cron_rules()) == 0
    handlers = repo.list_handlers(process_id=repo.list_processes()[0].id)
    assert len(handlers) == 0


def test_spawn_with_named_scoped_capabilities(tmp_path):
    """ProcsCapability.spawn() should create named grants with scope config."""
    from uuid import UUID
    from cogos.capabilities.procs import ProcsCapability

    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
    procs_cap = ProcsCapability(repo, parent.id)

    # Spawn with named capabilities — None means unscoped lookup by name
    result = procs_cap.spawn(
        name="child_worker",
        content="do work",
        capabilities={"dir": None},
    )
    assert result.name == "child_worker"
    child_proc = repo.get_process_by_name("child_worker")
    assert str(child_proc.parent_process) == str(parent.id)

    # Verify the grant
    child = repo.get_process(UUID(result.id))
    pcs = repo.list_process_capabilities(child.id)
    assert len(pcs) == 1
    assert pcs[0].name == "dir"
    assert pcs[0].config is None


def test_spawn_with_scoped_config(tmp_path):
    """Spawn with a scope config dict stored on the grant."""
    from uuid import UUID
    from unittest.mock import MagicMock
    from cogos.capabilities.procs import ProcsCapability

    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
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

    child = repo.get_process(UUID(result.id))
    pcs = repo.list_process_capabilities(child.id)
    assert len(pcs) == 1
    assert pcs[0].name == "workspace"
    assert pcs[0].config == {"prefix": "/readonly/", "ops": ["list", "read"]}


def test_spawn_multiple_grants_same_capability(tmp_path):
    """A process can have multiple named grants of the same capability."""
    from uuid import UUID
    from unittest.mock import MagicMock
    from cogos.capabilities.procs import ProcsCapability

    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    parent = repo.list_processes()[0]
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

    child = repo.get_process(UUID(result.id))
    pcs = repo.list_process_capabilities(child.id)
    assert len(pcs) == 2
    by_name = {pc.name: pc for pc in pcs}
    assert by_name["config"].config == {"prefix": "/config/", "ops": ["read"]}
    assert by_name["scratch"].config == {"prefix": "/scratch/", "ops": ["list", "read", "write"]}
