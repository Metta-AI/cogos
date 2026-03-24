"""Tests for Claude Code channel integration — system channels and IO registration."""

from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import ChannelMessage, Process, ProcessStatus
from cogos.lib.channels import SYSTEM_CHANNELS, ensure_system_channels


def _repo(tmp_path) -> SqliteRepository:
    return SqliteRepository(str(tmp_path))


def test_claude_code_system_channels_created(tmp_path):
    """io:claude-code:inbound and io:claude-code:outbound are created."""
    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    inbound = repo.get_channel_by_name("io:claude-code:inbound")
    assert inbound is not None
    assert inbound.inline_schema is not None
    assert "content" in inbound.inline_schema["fields"]
    assert "author" in inbound.inline_schema["fields"]

    outbound = repo.get_channel_by_name("io:claude-code:outbound")
    assert outbound is not None
    assert outbound.inline_schema is not None
    assert "content" in outbound.inline_schema["fields"]
    assert "channel" in outbound.inline_schema["fields"]


def test_claude_code_inbound_schema_validates(tmp_path):
    """Messages matching the inbound schema can be sent."""
    from cogos.channels.schema_validator import SchemaValidator

    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    ch = repo.get_channel_by_name("io:claude-code:inbound")
    assert ch is not None

    assert ch.inline_schema is not None
    validator = SchemaValidator(ch.inline_schema)
    validator.validate({
        "content": "Hello from Claude Code",
        "author": "user@example.com",
        "source": "claude-code-session",
        "metadata": {"session_id": "abc123"},
    })

    msg = ChannelMessage(
        channel=ch.id,
        sender_process=init_id,
        payload={
            "content": "test message",
            "author": "test",
            "source": "test",
            "metadata": {},
        },
    )
    msg_id = repo.append_channel_message(msg)
    assert msg_id is not None


def test_claude_code_outbound_schema_validates(tmp_path):
    """Messages matching the outbound schema can be sent."""
    from cogos.channels.schema_validator import SchemaValidator

    repo = _repo(tmp_path)
    init = Process(name="init", status=ProcessStatus.RUNNABLE, required_tags=["local"])
    init_id = repo.upsert_process(init)

    ensure_system_channels(repo, init_id)

    ch = repo.get_channel_by_name("io:claude-code:outbound")
    assert ch is not None

    assert ch.inline_schema is not None
    validator = SchemaValidator(ch.inline_schema)
    validator.validate({
        "content": "Response from CogOS",
        "channel": "io:claude-code:inbound",
        "metadata": {"trace_id": "xyz"},
    })

    msg = ChannelMessage(
        channel=ch.id,
        sender_process=init_id,
        payload={
            "content": "reply",
            "channel": "io:claude-code:inbound",
            "metadata": {},
        },
    )
    msg_id = repo.append_channel_message(msg)
    assert msg_id is not None


def test_claude_code_channels_in_system_registry():
    """Claude Code channels are in the SYSTEM_CHANNELS registry."""
    names = [ch["name"] for ch in SYSTEM_CHANNELS]
    assert "io:claude-code:inbound" in names
    assert "io:claude-code:outbound" in names


def test_claude_code_in_io_types():
    """claude-code is registered as an IO type."""
    from cogos.io.cli import IO_TYPES

    assert "claude-code" in IO_TYPES
    assert IO_TYPES["claude-code"] == "mcp_channel"
