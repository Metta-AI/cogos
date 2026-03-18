"""Tests for the Cog primitive: CogCapability, Coglet, CogletRuntime."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from cogos.capabilities.cog import CogCapability
from cogos.capabilities.coglet_runtime import CogletRun, CogletRuntimeCapability
from cogos.cog import (
    Coglet,
    CogletError,
    CogletStatus,
    MergeResult,
    PatchResult,
    TestResultInfo,
    load_cog_meta,
    load_coglet_meta,
    read_file_tree,
)
from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _make_cog_cap(repo, cog_name="test-cog") -> CogCapability:
    pid = uuid4()
    cap = CogCapability(repo, pid)
    return cap.scope(cog_name=cog_name)


# ---------------------------------------------------------------------------
# CogCapability.make_coglet
# ---------------------------------------------------------------------------

class TestCogMakeCoglet:
    def test_make_coglet_creates_coglet(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = _make_cog_cap(repo, "my-cog")
        result = cap.make_coglet("widget", files={"main.py": "print('hi')"})
        assert isinstance(result, Coglet)
        assert result.cog_name == "my-cog"
        assert result.name == "widget"

    def test_make_coglet_stores_files(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = _make_cog_cap(repo)
        cap.make_coglet("widget", files={"src/main.py": "x = 1", "README.md": "hello"})
        store = FileStore(repo)
        files = read_file_tree(store, "test-cog", "widget", "main")
        assert "src/main.py" in files
        assert "README.md" in files

    def test_make_coglet_stores_meta(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = _make_cog_cap(repo)
        cap.make_coglet("widget", entrypoint="main.md", mode="daemon",
                        files={"main.md": "content"})
        store = FileStore(repo)
        meta = load_coglet_meta(store, "test-cog", "widget")
        assert meta is not None
        assert meta.name == "widget"
        assert meta.entrypoint == "main.md"
        assert meta.mode == "daemon"

    def test_make_coglet_creates_cog_meta(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = _make_cog_cap(repo, "brand-new-cog")
        cap.make_coglet("first", files={"a.py": "1"})
        store = FileStore(repo)
        cog_meta = load_cog_meta(store, "brand-new-cog")
        assert cog_meta is not None
        assert cog_meta.name == "brand-new-cog"

    def test_make_coglet_idempotent(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = _make_cog_cap(repo)
        c1 = cap.make_coglet("widget", files={"v.txt": "v1"})
        c2 = cap.make_coglet("widget", files={"v.txt": "v2"})
        assert isinstance(c1, Coglet)
        assert isinstance(c2, Coglet)
        # Files should be updated
        store = FileStore(repo)
        files = read_file_tree(store, "test-cog", "widget", "main")
        assert files["v.txt"] == "v2"

    def test_make_coglet_requires_scope(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = CogCapability(repo, uuid4())
        with pytest.raises(PermissionError, match="cog_name"):
            cap.make_coglet("widget", files={})


# ---------------------------------------------------------------------------
# Coglet operations
# ---------------------------------------------------------------------------

def _make_coglet(tmp_path, files=None, test_command="true") -> Coglet:
    repo = _make_repo(tmp_path)
    cap = _make_cog_cap(repo, "test-cog")
    return cap.make_coglet("widget", test_command=test_command,
                           files=files or {"main.py": "def hello():\n    return 'world'\n"})


class TestCogletReadFile:
    def test_read_file(self, tmp_path):
        coglet = _make_coglet(tmp_path, files={"data.txt": "hello"})
        result = coglet.read_file("data.txt")
        assert result == "hello"

    def test_read_file_not_found(self, tmp_path):
        coglet = _make_coglet(tmp_path)
        result = coglet.read_file("missing.txt")
        assert isinstance(result, CogletError)

    def test_list_files(self, tmp_path):
        coglet = _make_coglet(tmp_path, files={"a.py": "1", "b.py": "2"})
        files = coglet.list_files()
        assert "a.py" in files
        assert "b.py" in files


class TestCogletPatchWorkflow:
    def _simple_diff(self):
        return (
            "--- a/main.py\n"
            "+++ b/main.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def hello():\n"
            "-    return 'world'\n"
            "+    return 'universe'\n"
        )

    def test_propose_patch(self, tmp_path):
        coglet = _make_coglet(tmp_path)
        result = coglet.propose_patch(self._simple_diff())
        assert isinstance(result, PatchResult)
        assert result.test_passed is True
        assert result.base_version == 0

    def test_merge_patch(self, tmp_path):
        coglet = _make_coglet(tmp_path)
        patch = coglet.propose_patch(self._simple_diff())
        assert isinstance(patch, PatchResult)
        merge = coglet.merge_patch(patch.patch_id)
        assert isinstance(merge, MergeResult)
        assert merge.merged is True
        assert merge.new_version == 1

    def test_discard_patch(self, tmp_path):
        coglet = _make_coglet(tmp_path)
        patch = coglet.propose_patch(self._simple_diff())
        assert isinstance(patch, PatchResult)
        result = coglet.discard_patch(patch.patch_id)
        assert result.discarded is True

    def test_get_status(self, tmp_path):
        coglet = _make_coglet(tmp_path)
        status = coglet.get_status()
        assert isinstance(status, CogletStatus)
        assert status.cog_name == "test-cog"
        assert status.name == "widget"
        assert status.version == 0

    def test_run_tests(self, tmp_path):
        coglet = _make_coglet(tmp_path, test_command="python -c 'print(\"ok\")'")
        result = coglet.run_tests()
        assert isinstance(result, TestResultInfo)
        assert result.passed is True

    def test_get_log(self, tmp_path):
        coglet = _make_coglet(tmp_path)
        coglet.propose_patch(self._simple_diff())
        log = coglet.get_log()
        assert len(log) >= 1
        assert log[0].action == "proposed"


# ---------------------------------------------------------------------------
# CogletRuntime
# ---------------------------------------------------------------------------

class TestCogletRuntime:
    def _setup(self, tmp_path):
        """Create a repo with procs capability, a cog, and an executable coglet."""
        from cogos.image.apply import apply_image
        from cogos.image.spec import ImageSpec

        repo = LocalRepository(str(tmp_path))
        spec = ImageSpec(capabilities=[
            {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
             "description": "", "instructions": "", "schema": None,
             "iam_role_arn": None, "metadata": None},
        ])
        apply_image(spec, repo)

        # Create a cog + coglet
        cap = _make_cog_cap(repo, "test-cog")
        coglet = cap.make_coglet("bot", entrypoint="main.md", mode="one_shot",
                                 files={"main.md": "You are a bot."})

        return repo, coglet

    def test_run_returns_coglet_run(self, tmp_path):
        from cogos.capabilities.process_handle import ProcessHandle
        from cogos.capabilities.procs import ProcsCapability
        from cogos.db.models import Process, ProcessMode, ProcessStatus
        from cogos.db.models import ProcessCapability as PCModel

        repo, coglet = self._setup(tmp_path)

        # Create parent process with procs capability
        parent = Process(name="parent", mode=ProcessMode.ONE_SHOT,
                         content="parent", status=ProcessStatus.RUNNABLE)
        parent_id = repo.upsert_process(parent)
        procs_cap_db = repo.get_capability_by_name("procs")
        pc = PCModel(process=parent_id, capability=procs_cap_db.id, name="procs")
        repo.create_process_capability(pc)
        procs = ProcsCapability(repo, parent_id)

        # Create runtime capability
        runtime = CogletRuntimeCapability(repo, parent_id)
        result = runtime.run(coglet, procs)

        assert isinstance(result, CogletRun), f"Expected CogletRun, got {type(result)}: {result}"
        handle = result.process()
        assert isinstance(handle, ProcessHandle)
        assert handle._process.name == "test-cog/bot"

    def test_run_data_only_coglet_fails(self, tmp_path):
        repo = _make_repo(tmp_path)
        cap = _make_cog_cap(repo, "test-cog")
        coglet = cap.make_coglet("data", files={"data.txt": "stuff"})
        runtime = CogletRuntimeCapability(repo, uuid4())
        result = runtime.run(coglet, None)
        assert isinstance(result, CogletError)
        assert "no entrypoint" in result.error


# ---------------------------------------------------------------------------
# Image-level: add_cog + make_default_coglet
# ---------------------------------------------------------------------------

class TestAddCog:
    def test_add_cog_in_image_spec(self):
        from cogos.image.spec import load_image
        spec = load_image(Path("images/cogent-v1"))
        cog_names = {c["name"] for c in spec.cogs}
        assert "recruiter" in cog_names
        assert "newsfromthefront" in cog_names

    def test_cog_apply_writes_boot_manifest(self, tmp_path):
        import json

        from cogos.files.store import FileStore
        from cogos.image.apply import apply_image
        from cogos.image.spec import load_image

        repo = LocalRepository(str(tmp_path))
        spec = load_image(Path("images/cogent-v1"))
        apply_image(spec, repo)

        fs = FileStore(repo)
        raw = fs.get_content("_boot/cog_processes.json")
        manifest = json.loads(raw)
        names = {e["name"] for e in manifest}
        assert "recruiter" in names
        assert "newsfromthefront" in names
