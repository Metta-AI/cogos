"""Test executor creates implicit process channel."""

from unittest.mock import MagicMock

from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_implicit_channel_created():
    """Verify _setup_capability_proxies creates implicit process channel."""
    from cogos.executor.handler import _setup_capability_proxies
    from cogos.sandbox.executor import VariableTable

    repo = MagicMock()
    repo.list_process_capabilities.return_value = []
    repo.get_channel_by_name.return_value = None  # channel doesn't exist yet

    proc = Process(
        name="test-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
    )
    vt = VariableTable()

    _setup_capability_proxies(vt, proc, repo)

    # Should have called upsert_channel to create implicit channel
    repo.upsert_channel.assert_called_once()
    call_args = repo.upsert_channel.call_args[0][0]
    assert call_args.name == "process:test-worker"
    assert call_args.channel_type.value == "implicit"


def test_implicit_channel_not_duplicated():
    """If channel already exists, upsert_channel is not called."""
    from cogos.executor.handler import _setup_capability_proxies
    from cogos.sandbox.executor import VariableTable

    repo = MagicMock()
    repo.list_process_capabilities.return_value = []
    repo.get_channel_by_name.return_value = MagicMock()  # channel exists

    proc = Process(
        name="test-worker",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
    )
    vt = VariableTable()

    _setup_capability_proxies(vt, proc, repo)

    repo.upsert_channel.assert_not_called()


def test_builtin_capabilities_include_channels_and_schemas():
    """Verify channels and schemas are registered in BUILTIN_CAPABILITIES."""
    from cogos.capabilities import BUILTIN_CAPABILITIES

    names = [c["name"] for c in BUILTIN_CAPABILITIES]
    assert "channels" in names
    assert "schemas" in names

    channels_cap = next(c for c in BUILTIN_CAPABILITIES if c["name"] == "channels")
    assert channels_cap["handler"] == "cogos.capabilities.channels.ChannelsCapability"

    schemas_cap = next(c for c in BUILTIN_CAPABILITIES if c["name"] == "schemas")
    assert schemas_cap["handler"] == "cogos.capabilities.schemas.SchemasCapability"
