from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus
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
