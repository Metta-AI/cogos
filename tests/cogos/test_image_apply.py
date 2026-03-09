from cogos.db.local_repository import LocalRepository
from cogos.image.spec import ImageSpec
from cogos.image.apply import apply_image


def _make_spec() -> ImageSpec:
    return ImageSpec(
        capabilities=[
            {"name": "files", "handler": "cogos.capabilities.files.FilesCapability",
             "description": "File store", "instructions": "", "input_schema": None,
             "output_schema": None, "iam_role_arn": None, "metadata": None},
        ],
        resources=[
            {"name": "lambda_slots", "type": "pool", "capacity": 5,
             "metadata": {"description": "Concurrent Lambda slots"}},
        ],
        processes=[
            {"name": "scheduler", "mode": "daemon", "content": "scheduler daemon",
             "code_key": "cogos/scheduler", "runner": "lambda", "model": None,
             "priority": 100.0, "capabilities": ["files"],
             "handlers": ["scheduler:tick"], "metadata": {}},
        ],
        cron_rules=[
            {"expression": "* * * * *", "event_type": "scheduler:tick"},
        ],
        files={"cogos/scheduler": "You are the scheduler."},
    )


def test_apply_creates_capabilities(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)

    caps = repo.list_capabilities()
    assert len(caps) == 1
    assert caps[0].name == "files"


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
    assert len(handlers) == 1
    assert handlers[0].event_pattern == "scheduler:tick"


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
    assert len(rules) == 1
    assert rules[0].expression == "* * * * *"
    assert rules[0].event_type == "scheduler:tick"


def test_apply_upsert_is_idempotent(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = _make_spec()
    apply_image(spec, repo)
    apply_image(spec, repo)

    assert len(repo.list_capabilities()) == 1
    assert len(repo.list_resources()) == 1
    assert len(repo.list_processes()) == 1
    assert len(repo.list_cron_rules()) == 1
    handlers = repo.list_handlers(process_id=repo.list_processes()[0].id)
    assert len(handlers) == 1
