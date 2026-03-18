from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.runtime.reboot import reboot


def test_reboot_clears_processes_and_creates_init(tmp_path):
    repo = LocalRepository(str(tmp_path))
    init_proc = Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
    repo.upsert_process(init_proc)
    child = Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING,
                    parent_process=init_proc.id)
    repo.upsert_process(child)

    result = reboot(repo)
    assert result["cleared_processes"] >= 2

    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"
    assert procs[0].status == ProcessStatus.RUNNABLE
    assert procs[0].executor == "python"


def test_reboot_preserves_files(tmp_path):
    from cogos.files.store import FileStore
    repo = LocalRepository(str(tmp_path))
    store = FileStore(repo)
    store.upsert("test/file.md", "hello", source="test")

    reboot(repo)

    assert store.get_content("test/file.md") == "hello"


def test_reboot_with_no_existing_processes(tmp_path):
    repo = LocalRepository(str(tmp_path))
    result = reboot(repo)
    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"


def test_image_declares_only_init_process(tmp_path):
    from cogos.image.apply import apply_image
    from cogos.image.spec import load_image

    repo = LocalRepository(str(tmp_path))
    image_dir = Path(__file__).resolve().parents[2] / "images" / "cogent-v1"
    spec = load_image(image_dir)
    apply_image(spec, repo)

    procs = repo.list_processes()
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

    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "", "instructions": "", "schema": None, "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)

    # Create channels
    for name in ["ch:a", "ch:b"]:
        repo.upsert_channel(Channel(name=name, channel_type=ChannelType.NAMED))

    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    parent_id = repo.upsert_process(parent)
    procs_cap = ProcsCapability(repo, parent_id)

    result = procs_cap.spawn(name="multi-sub", content="test", subscribe=["ch:a", "ch:b"])
    assert not hasattr(result, "error") or result.error is None

    child = repo.get_process_by_name("multi-sub")
    handlers = repo.list_handlers(process_id=child.id)
    assert len(handlers) == 2
