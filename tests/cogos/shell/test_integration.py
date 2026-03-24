"""Integration test — full registry, realistic workflow."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Capability, Process, ProcessMode, ProcessStatus
from cogos.files.store import FileStore
from cogos.shell.commands import ShellState, build_registry


def test_full_workflow(tmp_path):
    repo = LocalRepository(str(tmp_path))
    fs = FileStore(repo)
    fs.create("prompts/init.md", "You are a helpful assistant.")
    fs.create("config/system.yaml", "debug: true")
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    repo.upsert_process(
        Process(
            name="init",
            mode=ProcessMode.DAEMON,
            status=ProcessStatus.WAITING,
            required_tags=[],
        )
    )

    state = ShellState(cogent_name="dr.alpha", repo=repo, cwd="")
    reg = build_registry()

    # File navigation
    assert reg.dispatch(state, "pwd") == "/"
    output = reg.dispatch(state, "ls")
    assert output is not None
    assert "prompts/" in output
    reg.dispatch(state, "cd prompts")
    assert state.cwd == "prompts/"
    output = reg.dispatch(state, "ls")
    assert output is not None
    assert "init.md" in output
    output = reg.dispatch(state, "cat init.md")
    assert output is not None
    assert "helpful assistant" in output

    # Go back
    reg.dispatch(state, "cd /")
    assert state.cwd == ""

    # Process management
    output = reg.dispatch(state, "ps")
    assert output is not None
    assert "init" in output
    reg.dispatch(state, 'spawn worker --content "do stuff"')
    output = reg.dispatch(state, "ps")
    assert output is not None
    assert "worker" in output
    reg.dispatch(state, "kill worker")
    p = repo.get_process_by_name("worker")
    assert p is not None
    assert p.status == ProcessStatus.DISABLED

    # Capabilities
    output = reg.dispatch(state, "cap ls")
    assert output is not None
    assert "files" in output

    # Help
    output = reg.dispatch(state, "help")
    assert output is not None
    assert "ls" in output
    assert reg.dispatch(state, "exit") is None
