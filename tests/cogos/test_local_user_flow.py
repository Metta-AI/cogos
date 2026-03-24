"""Integration test that mirrors the README getting-started flow.

Boot the cogos image, verify status, send a channel message, run an executor
tick, and confirm the process dispatched and completed — all locally with a
fake executor (no Bedrock/AWS needed).
"""

from pathlib import Path

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    RunStatus,
)
from cogos.image.apply import apply_image
from cogos.image.spec import load_image
from cogos.runtime.local import run_local_tick

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = REPO_ROOT / "images" / "cogos"


def _noop_execute(process, event_data, run, config, repo, **kwargs):
    run.tokens_in = 10
    run.tokens_out = 5
    return run


def _boot(tmp_path) -> LocalRepository:
    repo = LocalRepository(str(tmp_path / "db"))
    spec = load_image(IMAGE_DIR)
    apply_image(spec, repo, clean=True)
    return repo


def _add_daemon_with_handler(repo) -> tuple[Process, Channel]:
    """Register a daemon process with a handler, simulating what init creates."""
    ch = Channel(name="test:trigger", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("test:trigger")

    p = Process(
        name="test-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=["local"],
    )
    repo.upsert_process(p)
    repo.create_handler(Handler(process=p.id, channel=ch.id, enabled=True))
    return p, ch


class TestBootState:
    """Verify image boot produces the expected local state."""

    def test_capabilities(self, tmp_path):
        repo = _boot(tmp_path)
        caps = {c.name for c in repo.list_capabilities()}
        assert len(caps) >= 7
        for expected in ("discord", "file", "channels", "procs"):
            assert expected in caps, f"Missing capability: {expected}"

    def test_init_process_exists(self, tmp_path):
        repo = _boot(tmp_path)
        procs = repo.list_processes()
        names = {p.name for p in procs}
        assert "init" in names
        init = next(p for p in procs if p.name == "init")
        assert init.status == ProcessStatus.RUNNABLE

    def test_channels(self, tmp_path):
        repo = _boot(tmp_path)
        ch_names = {ch.name for ch in repo.list_channels()}
        assert "io:stdin" in ch_names
        assert "io:stdout" in ch_names
        assert "io:stderr" in ch_names

    def test_files(self, tmp_path):
        repo = _boot(tmp_path)
        files = repo.list_files(prefix="mnt/boot/", limit=5)
        assert len(files) > 0

    def test_cog_manifests_written(self, tmp_path):
        import json

        from cogos.files.store import FileStore

        repo = _boot(tmp_path)
        fs = FileStore(repo)
        raw = fs.get_content("mnt/boot/_boot/cog_manifests.json")
        assert raw is not None
        manifests = json.loads(raw)
        names = {m["name"] for m in manifests}
        assert "diagnostics" in names


class TestExecutorFlow:
    """Test the local executor tick dispatches and completes processes."""

    def test_init_dispatched_on_first_tick(self, tmp_path):
        repo = _boot(tmp_path)
        executed = run_local_tick(repo, None, execute_fn=_noop_execute)
        assert executed >= 1

        runs = repo.list_runs(limit=5)
        assert len(runs) >= 1
        assert runs[0].status == RunStatus.COMPLETED

    def test_channel_message_triggers_daemon(self, tmp_path):
        repo = _boot(tmp_path)
        # Run init tick first to clear the runnable init process
        run_local_tick(repo, None, execute_fn=_noop_execute)

        p, ch = _add_daemon_with_handler(repo)

        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=p.id,
            payload={"content": "hello", "author": "tester"},
        ))

        executed = run_local_tick(repo, None, execute_fn=_noop_execute)
        assert executed == 1

        updated = repo.get_process(p.id)
        assert updated is not None
        assert updated.status == ProcessStatus.WAITING

    def test_run_records_token_counts(self, tmp_path):
        repo = _boot(tmp_path)
        run_local_tick(repo, None, execute_fn=_noop_execute)

        p, ch = _add_daemon_with_handler(repo)
        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=p.id,
            payload={"content": "test"},
        ))
        run_local_tick(repo, None, execute_fn=_noop_execute)

        runs = repo.list_runs(limit=10)
        daemon_runs = [r for r in runs if r.process == p.id]
        assert len(daemon_runs) == 1
        assert daemon_runs[0].tokens_in == 10
        assert daemon_runs[0].tokens_out == 5

    def test_disabled_process_not_dispatched(self, tmp_path):
        repo = _boot(tmp_path)
        run_local_tick(repo, None, execute_fn=_noop_execute)

        p, ch = _add_daemon_with_handler(repo)
        repo.update_process_status(p.id, ProcessStatus.DISABLED)

        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            sender_process=p.id,
            payload={"content": "should not trigger"},
        ))

        executed = run_local_tick(repo, None, execute_fn=_noop_execute)
        assert executed == 0

        updated = repo.get_process(p.id)
        assert updated is not None
        assert updated.status == ProcessStatus.DISABLED

    def test_no_work_returns_zero(self, tmp_path):
        repo = _boot(tmp_path)
        run_local_tick(repo, None, execute_fn=_noop_execute)

        executed = run_local_tick(repo, None, execute_fn=_noop_execute)
        assert executed == 0
