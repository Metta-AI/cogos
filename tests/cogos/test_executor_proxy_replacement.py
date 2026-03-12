"""Tests that _setup_capability_proxies uses real capability classes, not inline proxies."""

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.files import FilesCapability
from cogos.capabilities.procs import ProcsCapability
from cogos.capabilities.me import MeCapability
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.executor.handler import _setup_capability_proxies
from cogos.sandbox.executor import VariableTable


def _make_process():
    return Process(
        id=uuid4(),
        name="test-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNING,
        runner="lambda",
    )


def _make_cap_model(name, handler):
    cap = MagicMock()
    cap.id = uuid4()
    cap.name = name
    cap.enabled = True
    cap.handler = handler
    return cap


def _make_pc(cap_model, name=None, config=None):
    pc = MagicMock()
    pc.capability = cap_model.id
    pc.name = name or cap_model.name
    pc.config = config
    return pc


def _make_repo(cap_models=None, pcs=None):
    repo = MagicMock()
    pcs = pcs or []
    repo.list_process_capabilities.return_value = pcs

    models_by_id = {c.id: c for c in (cap_models or [])}
    repo.get_capability.side_effect = lambda cid: models_by_id.get(cid)
    return repo


class TestNoAmbientCapabilities:
    def test_no_bindings_means_no_capabilities(self):
        """A process with no capability bindings gets nothing except print."""
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo())
        assert vt.get("files") is None
        assert vt.get("procs") is None
        assert vt.get("channels") is None
        assert vt.get("me") is None
        assert vt.get("print") is print


class TestBoundCapabilities:
    def test_files_from_binding(self):
        cap = _make_cap_model("files", "cogos.capabilities.files.FilesCapability")
        pc = _make_pc(cap)
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo([cap], [pc]))
        assert isinstance(vt.get("files"), FilesCapability)

    def test_procs_from_binding(self):
        cap = _make_cap_model("procs", "cogos.capabilities.procs.ProcsCapability")
        pc = _make_pc(cap)
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo([cap], [pc]))
        assert isinstance(vt.get("procs"), ProcsCapability)

    def test_channels_from_binding(self):
        from cogos.capabilities.channels import ChannelsCapability
        cap = _make_cap_model("channels", "cogos.capabilities.channels.ChannelsCapability")
        pc = _make_pc(cap)
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo([cap], [pc]))
        assert isinstance(vt.get("channels"), ChannelsCapability)

    def test_me_from_binding(self):
        cap = _make_cap_model("me", "cogos.capabilities.me.MeCapability")
        pc = _make_pc(cap)
        run_id = uuid4()
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo([cap], [pc]), run_id=run_id)
        me = vt.get("me")
        assert isinstance(me, MeCapability)
        assert me.run_id == run_id

    def test_scoped_capability_from_config(self):
        """When ProcessCapability has config, the injected instance should be scoped."""
        cap = _make_cap_model("files", "cogos.capabilities.files.FilesCapability")
        pc = _make_pc(cap, name="workspace", config={"prefix": "/workspace/", "ops": ["list", "read"]})
        vt = VariableTable()
        _setup_capability_proxies(vt, _make_process(), _make_repo([cap], [pc]))

        workspace = vt.get("workspace")
        assert isinstance(workspace, FilesCapability)
        assert workspace._scope == {"prefix": "/workspace/", "ops": ["list", "read"]}
