from cogos.db.sqlite_repository import SqliteRepository


def test_creates_db_file(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert (tmp_path / "cogos.db").exists()


def test_tables_created(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    tables = repo.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    table_names = [t["name"] for t in tables]
    assert "cogos_process" in table_names
    assert "cogos_file" in table_names
    assert "cogos_run" in table_names


def test_epoch_starts_at_zero(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert repo.reboot_epoch == 0


def test_increment_epoch(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    assert repo.increment_epoch() == 1
    assert repo.increment_epoch() == 2
    assert repo.reboot_epoch == 2


def test_batch_is_transactional(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.set_meta("key1", "val1")
    try:
        with repo.batch():
            repo.set_meta("key2", "val2")
            raise ValueError("rollback")
    except ValueError:
        pass
    assert repo.get_meta("key1") is not None
    assert repo.get_meta("key2") is None


def test_meta_set_and_get(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.set_meta("foo", "bar")
    result = repo.get_meta("foo")
    assert result == {"key": "foo", "value": "bar"}


def test_clear_all(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.set_meta("key", "val")
    repo.clear_all()
    assert repo.get_meta("key") is None


def test_upsert_and_get_process(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="test", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    pid = repo.upsert_process(p)
    result = repo.get_process(pid)
    assert result is not None
    assert result.name == "test"


def test_get_process_by_name(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="named", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    result = repo.get_process_by_name("named")
    assert result is not None


def test_process_cascade_disable(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, parent_process=parent.id)
    repo.upsert_process(child)
    repo.update_process_status(parent.id, ProcessStatus.DISABLED)
    assert repo.get_process(child.id).status == ProcessStatus.DISABLED


def test_process_round_trip_json_fields(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="rt", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING,
                metadata={"key": "val"}, required_tags=["gpu"])
    repo.upsert_process(p)
    got = repo.get_process(p.id)
    assert got.metadata == {"key": "val"}
    assert got.required_tags == ["gpu"]


# ── File insert + get by key ─────────────────────────────

def test_file_insert_and_get_by_key(tmp_path):
    from cogos.db.models import File, FileVersion
    repo = SqliteRepository(str(tmp_path))
    f = File(key="vsm/test.py")
    repo.insert_file(f)
    fv = FileVersion(file_id=f.id, version=1, content="print('hi')", source="user")
    repo.insert_file_version(fv)
    got = repo.get_file_by_key("vsm/test.py")
    assert got is not None
    assert got.key == "vsm/test.py"
    active = repo.get_active_file_version(f.id)
    assert active is not None
    assert active.content == "print('hi')"


# ── grep_files with regex match ──────────────────────────

def test_grep_files(tmp_path):
    from cogos.db.models import File, FileVersion
    repo = SqliteRepository(str(tmp_path))
    f1 = File(key="src/a.py")
    repo.insert_file(f1)
    repo.insert_file_version(FileVersion(file_id=f1.id, version=1, content="def foo():\n    return 42"))
    f2 = File(key="src/b.py")
    repo.insert_file(f2)
    repo.insert_file_version(FileVersion(file_id=f2.id, version=1, content="x = 1\ny = 2"))
    results = repo.grep_files(r"def \w+")
    assert len(results) == 1
    assert results[0][0] == "src/a.py"
    assert "def foo" in results[0][1]


# ── Delivery create + mark_delivered ─────────────────────

def test_delivery_create_and_mark_delivered(tmp_path):
    from uuid import uuid4
    from cogos.db.models import Delivery, DeliveryStatus
    repo = SqliteRepository(str(tmp_path))
    from cogos.db.models import Process, ProcessMode, ProcessStatus, Channel, ChannelType, Handler
    p = Process(name="dlv_proc", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    ch = Channel(name="dlv_ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id, enabled=True)
    hid = repo.create_handler(h)
    from cogos.db.models import ChannelMessage
    msg = ChannelMessage(channel=ch.id, payload={"text": "hello"})
    repo.append_channel_message(msg)
    deliveries = repo.get_pending_deliveries(p.id)
    assert len(deliveries) == 1
    d = deliveries[0]
    run_id = uuid4()
    repo.mark_delivered(d.id, run_id)
    updated = repo.list_deliveries(handler_id=hid)
    assert updated[0].status == DeliveryStatus.DELIVERED


# ── Channel message append triggers delivery + process wake ──

def test_channel_message_wakes_process(tmp_path):
    from cogos.db.models import Process, ProcessMode, ProcessStatus, Channel, ChannelType, Handler, ChannelMessage
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="wake_proc", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    ch = Channel(name="wake_ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id, enabled=True)
    repo.create_handler(h)
    msg = ChannelMessage(channel=ch.id, payload={"data": 1})
    repo.append_channel_message(msg)
    proc = repo.get_process(p.id)
    assert proc.status == ProcessStatus.RUNNABLE


# ── Run create + complete ────────────────────────────────

def test_run_create_and_complete(tmp_path):
    from decimal import Decimal
    from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
    repo = SqliteRepository(str(tmp_path))
    p = Process(name="run_proc", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    run = Run(process=p.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    got = repo.get_run(run.id)
    assert got is not None
    assert got.status == RunStatus.RUNNING
    repo.complete_run(run.id, status=RunStatus.COMPLETED, tokens_in=10, tokens_out=5,
                      cost_usd=Decimal("0.01"), duration_ms=500)
    completed = repo.get_run(run.id)
    assert completed.status == RunStatus.COMPLETED
    assert completed.tokens_in == 10
    assert completed.completed_at is not None


# ── Executor register + select with tags ─────────────────

def test_executor_register_and_select(tmp_path):
    from cogos.db.models import Executor, ExecutorStatus
    repo = SqliteRepository(str(tmp_path))
    e1 = Executor(executor_id="exec-gpu-1", executor_tags=["gpu", "large"])
    repo.register_executor(e1)
    e2 = Executor(executor_id="exec-cpu-1", executor_tags=["cpu"])
    repo.register_executor(e2)
    got = repo.select_executor(required_tags=["gpu"])
    assert got is not None
    assert got.executor_id == "exec-gpu-1"
    got_none = repo.select_executor(required_tags=["tpu"])
    assert got_none is None


# ── Discord guild CRUD ───────────────────────────────────

def test_discord_guild_crud(tmp_path):
    from cogos.db.models.discord_metadata import DiscordGuild
    repo = SqliteRepository(str(tmp_path))
    guild = DiscordGuild(guild_id="g1", cogent_name="test-bot", name="Test Guild")
    repo.upsert_discord_guild(guild)
    got = repo.get_discord_guild("g1")
    assert got is not None
    assert got.name == "Test Guild"
    guilds = repo.list_discord_guilds(cogent_name="test-bot")
    assert len(guilds) == 1
    repo.delete_discord_guild("g1")
    assert repo.get_discord_guild("g1") is None
