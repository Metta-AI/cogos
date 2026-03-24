from pathlib import Path

from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.runtime.reboot import reboot


def test_reboot_clears_processes_and_creates_init(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    init_proc = Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    repo.upsert_process(init_proc)
    child = Process(
        name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, parent_process=init_proc.id
    )
    repo.upsert_process(child)

    result = reboot(repo)
    assert result["cleared_processes"] >= 2

    procs = repo.list_processes()
    assert procs is not None
    assert len(procs) == 1
    assert procs[0].name == "init"
    assert procs[0].status == ProcessStatus.RUNNABLE
    assert procs[0].executor == "python"


def test_reboot_preserves_old_processes_in_previous_epoch(tmp_path):
    from cogos.db.models import ALL_EPOCHS, Run, RunStatus

    repo = SqliteRepository(str(tmp_path))
    old = Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(old)
    run = Run(process=old.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    reboot(repo)

    # Current epoch: only init
    procs = repo.list_processes()
    assert procs is not None
    assert len(procs) == 1
    assert procs[0].name == "init"

    # All epochs: old scheduler (epoch 0), old init (epoch 0, disabled), new init (epoch 1)
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    assert all_procs is not None
    names = {p.name for p in all_procs}
    assert "scheduler" in names
    assert "init" in names

    # Old runs still visible in all epochs
    all_runs = repo.list_runs(epoch=ALL_EPOCHS)
    assert all_runs is not None
    assert len(all_runs) == 1

    # Current epoch runs: none
    current_runs = repo.list_runs()
    assert current_runs is not None
    assert len(current_runs) == 0


def test_reboot_logs_operation(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.upsert_process(Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED))

    reboot(repo)

    ops = repo.list_operations()
    assert ops is not None
    assert len(ops) == 1
    assert ops[0].type == "reboot"
    assert ops[0].epoch == 1


def test_reboot_epoch_increments(tmp_path):
    repo = SqliteRepository(str(tmp_path))

    reboot(repo)
    assert repo.reboot_epoch == 1

    reboot(repo)
    assert repo.reboot_epoch == 2

    procs = repo.list_processes()
    assert procs is not None
    assert len(procs) == 1  # only the latest init


def test_reboot_preserves_files(tmp_path):
    from cogos.files.store import FileStore

    repo = SqliteRepository(str(tmp_path))
    store = FileStore(repo)
    store.upsert("test/file.md", "hello", source="test")

    reboot(repo)

    assert store.get_content("test/file.md") == "hello"


def test_reboot_with_no_existing_processes(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    result = reboot(repo)
    procs = repo.list_processes()
    assert procs is not None
    assert len(procs) == 1
    assert procs[0].name == "init"


def test_image_declares_only_init_process(tmp_path):
    from cogos.image.apply import apply_image
    from cogos.image.spec import load_image

    repo = SqliteRepository(str(tmp_path))
    image_dir = Path(__file__).resolve().parents[2] / "images" / "cogos"
    spec = load_image(image_dir)
    apply_image(spec, repo)

    procs = repo.list_processes()
    assert procs is not None
    top_level = [p for p in procs if p.parent_process is None]
    # Only init — cog processes are now spawned by init.py at runtime
    assert len(top_level) == 1
    init_proc = top_level[0]
    assert init_proc.name == "init"
    assert init_proc.executor == "python"
    assert init_proc.priority >= 100


def test_spawn_with_multiple_subscribe(tmp_path):
    """Verify spawn() accepts a list of subscribe channels."""
    from cogos.capabilities.procs import ProcsCapability
    from cogos.image.apply import apply_image
    from cogos.image.spec import ImageSpec

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

    # Create channels
    for name in ["ch:a", "ch:b"]:
        repo.upsert_channel(Channel(name=name, channel_type=ChannelType.NAMED))

    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    procs_cap = ProcsCapability(repo, parent_id)

    result = procs_cap.spawn(name="multi-sub", content="test", subscribe=["ch:a", "ch:b"])
    from cogos.capabilities.procs import ProcessError

    assert not isinstance(result, ProcessError)

    child = repo.get_process_by_name("multi-sub")
    assert child is not None
    handlers = repo.list_handlers(process_id=child.id)
    assert handlers is not None
    assert len(handlers) == 2
