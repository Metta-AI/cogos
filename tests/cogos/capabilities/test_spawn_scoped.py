"""Integration test: spawn a child process with scoped capabilities."""

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.channels import ChannelsCapability
from cogos.capabilities.files import FilesCapability
from cogos.capabilities.procs import ProcsCapability


def test_spawn_with_scoped_capabilities():
    """Verify spawn reads _scope from capability instances and stores as config."""
    repo = MagicMock()
    repo.upsert_process.return_value = uuid4()

    # Set up capability model lookups
    files_cap_model = MagicMock()
    files_cap_model.id = uuid4()
    files_cap_model.enabled = True

    channels_cap_model = MagicMock()
    channels_cap_model.id = uuid4()
    channels_cap_model.enabled = True

    def lookup(name):
        return {"files": files_cap_model, "channels": channels_cap_model}.get(name)
    repo.get_capability_by_name.side_effect = lookup

    # Parent holds unscoped grants for both capability types
    parent_files_grant = MagicMock()
    parent_files_grant.capability = files_cap_model.id
    parent_files_grant.config = None

    parent_channels_grant = MagicMock()
    parent_channels_grant.capability = channels_cap_model.id
    parent_channels_grant.config = None

    repo.list_process_capabilities.return_value = [parent_files_grant, parent_channels_grant]

    procs = ProcsCapability(repo, uuid4())
    files = FilesCapability(repo, uuid4())
    channels = ChannelsCapability(repo, uuid4())

    # Spawn with scoped capabilities
    result = procs.spawn(
        name="worker",
        content="do work",
        capabilities={
            "workspace": files.scope(prefix="/workspace/", ops=["list", "read"]),
            "channels": channels,  # unscoped
        },
    )

    assert hasattr(result, "id")

    # Verify ProcessCapability was created with correct config
    calls = repo.create_process_capability.call_args_list
    assert len(calls) == 2

    # Find the workspace grant
    workspace_call = [c for c in calls if c[0][0].name == "workspace"][0]
    pc = workspace_call[0][0]
    assert pc.config == {"prefix": "/workspace/", "ops": ["list", "read"]}

    # Find the channels grant — unscoped should have None or empty config
    channels_call = [c for c in calls if c[0][0].name == "channels"][0]
    pc_channels = channels_call[0][0]
    assert pc_channels.config is None  # empty _scope → stored as None
