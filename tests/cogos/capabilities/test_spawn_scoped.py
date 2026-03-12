"""Integration test: spawn a child process with scoped capabilities."""

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.events import EventsCapability
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

    events_cap_model = MagicMock()
    events_cap_model.id = uuid4()
    events_cap_model.enabled = True

    def lookup(name):
        return {"files": files_cap_model, "events": events_cap_model}.get(name)
    repo.get_capability_by_name.side_effect = lookup

    procs = ProcsCapability(repo, uuid4())
    files = FilesCapability(repo, uuid4())
    events = EventsCapability(repo, uuid4())

    # Spawn with scoped capabilities
    result = procs.spawn(
        name="worker",
        content="do work",
        capabilities={
            "workspace": files.scope(prefix="/workspace/", ops=["list", "read"]),
            "events": events,  # unscoped
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

    # Find the events grant — unscoped should have None or empty config
    events_call = [c for c in calls if c[0][0].name == "events"][0]
    pc_events = events_call[0][0]
    assert pc_events.config is None  # empty _scope → stored as None
