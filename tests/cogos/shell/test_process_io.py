"""Tests for per-process IO: tty field, spawn channels, MeCapability, ProcessHandle, executor."""

from cogos.capabilities.me import MeCapability
from cogos.capabilities.process_handle import ProcessHandle
from cogos.capabilities.procs import ProcessError, ProcsCapability
from cogos.db.models import (
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
)
from cogos.db.sqlite_repository import SqliteRepository
from cogos.executor.handler import _publish_process_io

# ── Process tty field ─────────────────────────────────────────


def test_process_tty_defaults_false():
    p = Process(name="test", mode=ProcessMode.ONE_SHOT)
    assert p.tty is False


def test_process_tty_persists(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="test", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, tty=True)
    repo.upsert_process(p)
    got = repo.get_process_by_name("test")
    assert got is not None
    assert got.tty is True


# ── Spawn creates io channels ────────────────────────────────


def _spawn_setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    cap = Capability(name="procs", handler="cogos.capabilities.procs.ProcsCapability", enabled=True)
    repo.upsert_capability(cap)
    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(parent)
    repo.create_process_capability(ProcessCapability(process=parent.id, capability=cap.id, name="procs"))
    return repo, ProcsCapability(repo, parent.id)  # type: ignore[arg-type]


def test_spawn_creates_stdio_channels(tmp_path):
    repo, procs = _spawn_setup(tmp_path)
    _handle = procs.spawn("worker", content="do stuff")
    for stream in ("stdin", "stdout", "stderr"):
        assert repo.get_channel_by_name(f"process:worker:{stream}") is not None


def test_spawn_with_tty(tmp_path):
    repo, procs = _spawn_setup(tmp_path)
    procs.spawn("tty-worker", content="x", tty=True)
    got = repo.get_process_by_name("tty-worker")
    assert got is not None
    assert got.tty is True


# ── MeCapability stdout/stderr/stdin ─────────────────────────


def _me_setup(tmp_path, *, tty=False):
    repo = SqliteRepository(str(tmp_path))
    proc = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, tty=tty)
    repo.upsert_process(proc)
    for stream in ("stdin", "stdout", "stderr"):
        repo.upsert_channel(
            Channel(name=f"process:worker:{stream}", owner_process=proc.id, channel_type=ChannelType.NAMED)
        )
    for stream in ("stdout", "stderr"):
        repo.upsert_channel(Channel(name=f"io:{stream}", channel_type=ChannelType.NAMED))
    repo.upsert_channel(Channel(name="io:stdin:worker", owner_process=proc.id, channel_type=ChannelType.NAMED))
    return repo, proc, MeCapability(repo, proc.id)


def test_me_stdout(tmp_path):
    repo, _, me = _me_setup(tmp_path)
    me.stdout("hello")
    ch = repo.get_channel_by_name("process:worker:stdout")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 1
    assert msgs[0].payload["text"] == "hello"


def test_me_stderr(tmp_path):
    repo, _, me = _me_setup(tmp_path)
    me.stderr("oops")
    ch = repo.get_channel_by_name("process:worker:stderr")
    assert ch is not None
    assert repo.list_channel_messages(ch.id)[0].payload["text"] == "oops"


def test_me_stdin(tmp_path):
    repo, _, me = _me_setup(tmp_path)
    ch = repo.get_channel_by_name("io:stdin:worker")
    assert ch is not None
    repo.append_channel_message(ChannelMessage(channel=ch.id, sender_process=None, payload={"text": "input"}))
    assert me.stdin() == "input"


def test_me_stdin_empty(tmp_path):
    _, _, me = _me_setup(tmp_path)
    assert me.stdin() is None


def test_me_stdout_tty_forwards(tmp_path):
    repo, _, me = _me_setup(tmp_path, tty=True)
    me.stdout("hello tty")
    ch = repo.get_channel_by_name("io:stdout")
    assert ch is not None
    assert len(repo.list_channel_messages(ch.id)) == 1


def test_me_stdout_no_tty_no_forward(tmp_path):
    repo, _, me = _me_setup(tmp_path, tty=False)
    me.stdout("hello")
    ch = repo.get_channel_by_name("io:stdout")
    assert ch is not None
    assert len(repo.list_channel_messages(ch.id)) == 0


# ── ProcessHandle stdin/stdout/stderr ────────────────────────


def _handle_setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, parent_process=parent.id)
    repo.upsert_process(child)
    for stream in ("stdin", "stdout", "stderr"):
        repo.upsert_channel(
            Channel(name=f"process:child:{stream}", owner_process=child.id, channel_type=ChannelType.NAMED)
        )
    return repo, ProcessHandle(
        repo=repo, caller_process_id=parent.id, process=child, send_channel=None, recv_channel=None
    )


def test_handle_stdin_writes(tmp_path):
    repo, handle = _handle_setup(tmp_path)
    handle.stdin("hello child")
    ch = repo.get_channel_by_name("process:child:stdin")
    assert ch is not None
    assert repo.list_channel_messages(ch.id)[0].payload["text"] == "hello child"


def test_handle_stdout_reads(tmp_path):
    repo, handle = _handle_setup(tmp_path)
    ch = repo.get_channel_by_name("process:child:stdout")
    assert ch is not None
    repo.append_channel_message(ChannelMessage(channel=ch.id, sender_process=None, payload={"text": "output"}))
    assert handle.stdout() == "output"


def test_handle_stdout_empty(tmp_path):
    _, handle = _handle_setup(tmp_path)
    assert handle.stdout() is None


# ── _publish_process_io ──────────────────────────────────────


def _pio_setup(tmp_path, *, tty=False):
    repo = SqliteRepository(str(tmp_path))
    proc = Process(name="test-proc", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, tty=tty)
    repo.upsert_process(proc)
    for stream in ("stdout", "stderr"):
        repo.upsert_channel(
            Channel(name=f"process:test-proc:{stream}", owner_process=proc.id, channel_type=ChannelType.NAMED)
        )
        repo.upsert_channel(Channel(name=f"io:{stream}", channel_type=ChannelType.NAMED))
    return repo, proc


def test_publish_process_io_writes_to_process_channel(tmp_path):
    repo, proc = _pio_setup(tmp_path)
    _publish_process_io(repo, proc, "stdout", "hello")
    ch = repo.get_channel_by_name("process:test-proc:stdout")
    assert ch is not None
    assert len(repo.list_channel_messages(ch.id)) == 1


def test_publish_process_io_no_tty_no_global(tmp_path):
    repo, proc = _pio_setup(tmp_path, tty=False)
    _publish_process_io(repo, proc, "stdout", "hello")
    ch = repo.get_channel_by_name("io:stdout")
    assert ch is not None
    assert len(repo.list_channel_messages(ch.id)) == 0


def test_publish_process_io_tty_forwards(tmp_path):
    repo, proc = _pio_setup(tmp_path, tty=True)
    _publish_process_io(repo, proc, "stdout", "hello tty")
    ch = repo.get_channel_by_name("io:stdout")
    assert ch is not None
    assert len(repo.list_channel_messages(ch.id)) == 1


# ── Integration: parent-child stdio ──────────────────────────


def test_parent_child_stdio(tmp_path):
    repo, procs = _spawn_setup(tmp_path)
    handle = procs.spawn("child", content="do work")
    assert not isinstance(handle, ProcessError)

    handle.stdin("input data")

    child_proc = repo.get_process_by_name("child")
    assert child_proc is not None
    me = MeCapability(repo, child_proc.id)
    assert me.stdin() == "input data"

    me.stdout("result data")
    assert handle.stdout() == "result data"


def test_tty_forwarding_e2e(tmp_path):
    repo, procs = _spawn_setup(tmp_path)
    for name in ("io:stdout", "io:stderr"):
        repo.upsert_channel(Channel(name=name, channel_type=ChannelType.NAMED))

    _handle = procs.spawn("tty-child", content="x", tty=True)
    child_proc = repo.get_process_by_name("tty-child")
    assert child_proc is not None
    me = MeCapability(repo, child_proc.id)
    me.stdout("visible output")

    ch1 = repo.get_channel_by_name("process:tty-child:stdout")
    assert ch1 is not None
    assert len(repo.list_channel_messages(ch1.id)) == 1
    ch2 = repo.get_channel_by_name("io:stdout")
    assert ch2 is not None
    assert len(repo.list_channel_messages(ch2.id)) == 1
