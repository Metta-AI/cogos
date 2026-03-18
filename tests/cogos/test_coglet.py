"""Tests for the coglet core module and capabilities."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from cogos.capabilities.coglet import (
    CogletCapability,
    CogletStatus,
    DiscardResult,
    MergeResult,
    PatchResult,
    PatchSummary,
    TestResultInfo,
)
from cogos.capabilities.coglet_factory import (
    CogletError,
    CogletFactoryCapability,
    CogletInfo,
    DeleteResult,
    _load_meta,
    _save_meta,
)
from cogos.coglet import (
    CogletMeta,
    LogEntry,
    PatchInfo,
    apply_diff,
    delete_file_tree,
    read_file_tree,
    run_tests,
    write_file_tree,
)
from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestCogletMeta:
    def test_defaults(self):
        m = CogletMeta(name="widget", test_command="pytest")
        assert m.name == "widget"
        assert m.test_command == "pytest"
        assert m.executor == "subprocess"
        assert m.timeout_seconds == 60
        assert m.version == 0
        assert m.patches == {}
        # id should be a valid uuid string
        assert len(m.id) == 36
        # created_at should be an ISO timestamp
        assert "T" in m.created_at

    def test_json_roundtrip(self):
        m = CogletMeta(name="widget", test_command="pytest")
        data = m.model_dump_json()
        m2 = CogletMeta.model_validate_json(data)
        assert m == m2

    def test_patches_dict(self):
        p = PatchInfo(base_version=1, test_passed=True, test_output="ok")
        m = CogletMeta(name="w", test_command="pytest", patches={"p1": p})
        assert m.patches["p1"].test_passed is True


class TestPatchInfo:
    def test_creation(self):
        p = PatchInfo(base_version=3, test_passed=False, test_output="fail")
        assert p.base_version == 3
        assert p.test_passed is False
        assert p.test_output == "fail"
        assert "T" in p.created_at

    def test_defaults(self):
        p = PatchInfo(base_version=0, test_passed=True)
        assert p.test_output == ""


class TestLogEntry:
    def test_creation(self):
        e = LogEntry(action="proposed", patch_id="abc")
        assert e.action == "proposed"
        assert e.patch_id == "abc"
        assert e.version is None
        assert "T" in e.timestamp


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


class TestRunTests:
    def test_passing(self):
        result = run_tests(
            "echo hello",
            {"main.py": "print('hello')"},
        )
        assert result.passed is True
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_failing(self):
        result = run_tests(
            "exit 1",
            {"main.py": "x = 1"},
        )
        assert result.passed is False
        assert result.exit_code == 1

    def test_timeout(self):
        result = run_tests(
            "sleep 10",
            {},
            timeout_seconds=1,
        )
        assert result.passed is False
        assert result.exit_code == -1

    def test_files_materialized(self):
        result = run_tests(
            "cat sub/data.txt",
            {"sub/data.txt": "content123"},
        )
        assert result.passed is True
        assert "content123" in result.output


# ---------------------------------------------------------------------------
# File tree helpers
# ---------------------------------------------------------------------------


class TestFileTree:
    def _store(self, tmp_path) -> FileStore:
        repo = LocalRepository(str(tmp_path))
        return FileStore(repo)

    def test_write_read_roundtrip(self, tmp_path):
        store = self._store(tmp_path)
        files = {"main.py": "print(1)", "lib/util.py": "x = 2"}
        write_file_tree(store, "cog1", "main", files)
        result = read_file_tree(store, "cog1", "main")
        assert result == files

    def test_read_nonexistent_returns_empty(self, tmp_path):
        store = self._store(tmp_path)
        result = read_file_tree(store, "missing", "main")
        assert result == {}

    def test_write_read_patch_branch(self, tmp_path):
        store = self._store(tmp_path)
        main_files = {"main.py": "v1"}
        patch_files = {"main.py": "v2", "new.py": "added"}
        write_file_tree(store, "cog1", "main", main_files)
        write_file_tree(store, "cog1", "patch/p1", patch_files)

        assert read_file_tree(store, "cog1", "main") == main_files
        assert read_file_tree(store, "cog1", "patch/p1") == patch_files

    def test_delete_file_tree(self, tmp_path):
        store = self._store(tmp_path)
        write_file_tree(store, "cog1", "main", {"a.py": "1", "b.py": "2"})
        count = delete_file_tree(store, "cog1", "main")
        assert count == 2
        assert read_file_tree(store, "cog1", "main") == {}


# ---------------------------------------------------------------------------
# Diff application
# ---------------------------------------------------------------------------


class TestApplyDiff:
    def test_modify_file(self):
        files = {"hello.py": "line1\nline2\nline3"}
        diff = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
            " line3"
        )
        result = apply_diff(files, diff)
        assert result["hello.py"] == "line1\nline2_modified\nline3"

    def test_add_file(self):
        files = {"existing.py": "code"}
        diff = (
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world"
        )
        result = apply_diff(files, diff)
        assert "new.py" in result
        assert result["new.py"] == "hello\nworld"
        assert result["existing.py"] == "code"

    def test_delete_file(self):
        files = {"remove.py": "gone", "keep.py": "stay"}
        diff = (
            "--- a/remove.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-gone"
        )
        result = apply_diff(files, diff)
        assert "remove.py" not in result
        assert result["keep.py"] == "stay"

    def test_invalid_diff_raises(self):
        with pytest.raises(ValueError):
            apply_diff({}, "not a diff at all")

    def test_modify_nonexistent_raises(self):
        diff = (
            "--- a/missing.py\n"
            "+++ b/missing.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new"
        )
        with pytest.raises(ValueError, match="not in tree"):
            apply_diff({}, diff)


# ---------------------------------------------------------------------------
# Helper for capability tests
# ---------------------------------------------------------------------------

_DEFAULT_FILES = {
    "src/main.py": "def hello():\n    return 'world'\n",
    "tests/test_main.py": "exec(open('src/main.py').read())\nassert hello() == 'world'\n",
}


def _create_test_coglet(
    tmp_path,
    files=None,
    test_command="python -c 'assert True'",
):
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletFactoryCapability(repo, pid)
    if files is None:
        files = dict(_DEFAULT_FILES)
    result = cap.create(name="test-coglet", test_command=test_command, files=files)
    assert isinstance(result, CogletInfo)
    return repo, result.coglet_id


# ---------------------------------------------------------------------------
# CogletFactoryCapability tests
# ---------------------------------------------------------------------------


class TestCogletFactoryCapabilityCreate:
    def test_create_returns_coglet_info(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        assert coglet_id  # non-empty
        assert len(coglet_id) == 36  # uuid

    def test_create_stores_files(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        store = FileStore(repo)
        tree = read_file_tree(store, coglet_id, "main")
        assert "src/main.py" in tree
        assert "tests/test_main.py" in tree

    def test_create_with_passing_tests(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        result = cap.create(
            name="pass-coglet",
            test_command="python -c 'print(\"ok\")'",
            files={"main.py": "x = 1\n"},
        )
        assert isinstance(result, CogletInfo)
        assert result.test_passed is True
        assert result.version == 0

    def test_create_with_failing_tests(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        result = cap.create(
            name="fail-coglet",
            test_command="python -c 'raise Exception(\"boom\")'",
            files={"main.py": "x = 1\n"},
        )
        assert isinstance(result, CogletInfo)
        assert result.test_passed is False
        assert "boom" in result.test_output

    def test_create_saves_meta(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        store = FileStore(repo)
        meta = _load_meta(store, coglet_id)
        assert meta is not None
        assert meta.name == "test-coglet"
        assert meta.id == coglet_id


class TestCogletFactoryCapabilityList:
    def test_list_returns_all(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        cap.create(name="a", test_command="true", files={"a.py": "1"})
        cap.create(name="b", test_command="true", files={"b.py": "2"})
        result = cap.list()
        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"a", "b"}

    def test_list_empty(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        assert cap.list() == []


class TestCogletFactoryCapabilityGet:
    def test_get_existing(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        result = cap.get(coglet_id)
        assert isinstance(result, CogletInfo)
        assert result.coglet_id == coglet_id
        assert result.name == "test-coglet"

    def test_get_missing(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        result = cap.get("nonexistent")
        assert isinstance(result, CogletError)
        assert "not found" in result.error


class TestCogletFactoryCapabilityDelete:
    def test_delete_removes_files(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        result = cap.delete(coglet_id)
        assert isinstance(result, DeleteResult)
        assert result.deleted is True
        assert result.coglet_id == coglet_id
        # Verify files are gone
        store = FileStore(repo)
        tree = read_file_tree(store, coglet_id, "main")
        assert tree == {}
        assert _load_meta(store, coglet_id) is None

    def test_delete_missing(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletFactoryCapability(repo, pid)
        result = cap.delete("nonexistent")
        assert isinstance(result, CogletError)


# ---------------------------------------------------------------------------
# CogletCapability tests
# ---------------------------------------------------------------------------


def _make_coglet_cap(repo, coglet_id):
    """Create a CogletCapability scoped to coglet_id."""
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    return cap.scope(coglet_id=coglet_id)


def _simple_diff():
    """A diff that modifies src/main.py."""
    return (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def hello():\n"
        "-    return 'world'\n"
        "+    return 'universe'\n"
    )


class TestCogletCapabilityProposePatch:
    def test_propose_passing(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path,
            test_command="python -c 'assert True'",
        )
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.propose_patch(_simple_diff())
        assert isinstance(result, PatchResult)
        assert result.test_passed is True
        assert result.base_version == 0
        assert len(result.patch_id) == 36

    def test_propose_failing(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path,
            test_command="python -c 'raise Exception(\"fail\")'",
        )
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.propose_patch(_simple_diff())
        assert isinstance(result, PatchResult)
        assert result.test_passed is False

    def test_propose_invalid_diff(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.propose_patch("not a valid diff")
        assert isinstance(result, CogletError)
        assert "diff" in result.error.lower() or "Failed" in result.error

    def test_propose_stores_patch_files(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.propose_patch(_simple_diff())
        assert isinstance(result, PatchResult)
        # Check patch files exist
        store = FileStore(repo)
        patch_files = read_file_tree(store, coglet_id, f"patches/{result.patch_id}")
        assert "src/main.py" in patch_files
        assert "universe" in patch_files["src/main.py"]


class TestCogletCapabilityMergePatch:
    def test_merge_success(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path, test_command="python -c 'assert True'"
        )
        cap = _make_coglet_cap(repo, coglet_id)
        patch = cap.propose_patch(_simple_diff())
        assert isinstance(patch, PatchResult)
        assert patch.test_passed is True

        merge = cap.merge_patch(patch.patch_id)
        assert isinstance(merge, MergeResult)
        assert merge.merged is True
        assert merge.new_version == 1

        # Verify main updated
        store = FileStore(repo)
        main_files = read_file_tree(store, coglet_id, "main")
        assert "universe" in main_files["src/main.py"]

    def test_merge_conflict_detection(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path, test_command="python -c 'assert True'"
        )
        cap = _make_coglet_cap(repo, coglet_id)

        # Create two patches at the same base version
        patch1 = cap.propose_patch(_simple_diff())
        assert isinstance(patch1, PatchResult)

        # Merge the first patch — version bumps to 1
        merge1 = cap.merge_patch(patch1.patch_id)
        assert isinstance(merge1, MergeResult)
        assert merge1.merged is True

        # Create a second patch — now at base_version 1
        diff2 = (
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def hello():\n"
            "-    return 'universe'\n"
            "+    return 'galaxy'\n"
        )
        patch2 = cap.propose_patch(diff2)
        assert isinstance(patch2, PatchResult)

        # Merge second patch — should succeed since base matches
        merge2 = cap.merge_patch(patch2.patch_id)
        assert isinstance(merge2, MergeResult)
        assert merge2.merged is True
        assert merge2.new_version == 2

    def test_merge_rejects_stale_base(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path, test_command="python -c 'assert True'"
        )
        cap = _make_coglet_cap(repo, coglet_id)

        # Create two patches at version 0
        patch1 = cap.propose_patch(_simple_diff())
        patch2 = cap.propose_patch(_simple_diff())
        assert isinstance(patch1, PatchResult)
        assert isinstance(patch2, PatchResult)

        # Merge first — bumps version to 1
        merge1 = cap.merge_patch(patch1.patch_id)
        assert isinstance(merge1, MergeResult)
        assert merge1.merged is True

        # Try to merge second — base_version=0, current=1
        merge2 = cap.merge_patch(patch2.patch_id)
        assert isinstance(merge2, MergeResult)
        assert merge2.merged is False
        assert merge2.conflict is True
        assert merge2.current_version == 1
        assert merge2.base_version == 0

    def test_merge_rejects_failing_tests(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path, test_command="python -c 'raise Exception(\"nope\")'",
        )
        cap = _make_coglet_cap(repo, coglet_id)
        patch = cap.propose_patch(_simple_diff())
        assert isinstance(patch, PatchResult)
        assert patch.test_passed is False

        result = cap.merge_patch(patch.patch_id)
        assert isinstance(result, CogletError)
        assert "failing" in result.error.lower()


class TestCogletCapabilityDiscardPatch:
    def test_discard(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        patch = cap.propose_patch(_simple_diff())
        assert isinstance(patch, PatchResult)

        result = cap.discard_patch(patch.patch_id)
        assert isinstance(result, DiscardResult)
        assert result.discarded is True
        assert result.patch_id == patch.patch_id

        # Verify patch files are gone
        store = FileStore(repo)
        patch_files = read_file_tree(store, coglet_id, f"patches/{patch.patch_id}")
        assert patch_files == {}

    def test_discard_nonexistent(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.discard_patch("nonexistent-patch")
        assert isinstance(result, CogletError)


class TestCogletCapabilityFiles:
    def test_list_files_main(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        files = cap.list_files()
        assert "src/main.py" in files
        assert "tests/test_main.py" in files

    def test_list_files_patch(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        patch = cap.propose_patch(_simple_diff())
        assert isinstance(patch, PatchResult)
        files = cap.list_files(patch_id=patch.patch_id)
        assert "src/main.py" in files

    def test_read_file_main(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        content = cap.read_file("src/main.py")
        assert isinstance(content, str)
        assert "hello" in content

    def test_read_file_patch(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        patch = cap.propose_patch(_simple_diff())
        assert isinstance(patch, PatchResult)
        content = cap.read_file("src/main.py", patch_id=patch.patch_id)
        assert isinstance(content, str)
        assert "universe" in content

    def test_read_file_not_found(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.read_file("nonexistent.py")
        assert isinstance(result, CogletError)


class TestCogletCapabilityStatus:
    def test_get_status(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        status = cap.get_status()
        assert isinstance(status, CogletStatus)
        assert status.coglet_id == coglet_id
        assert status.name == "test-coglet"
        assert status.version == 0
        assert status.patch_count == 0

    def test_get_status_with_patches(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        cap.propose_patch(_simple_diff())
        status = cap.get_status()
        assert isinstance(status, CogletStatus)
        assert status.patch_count == 1


class TestCogletCapabilityRunTests:
    def test_run_tests_on_main(self, tmp_path):
        repo, coglet_id = _create_test_coglet(
            tmp_path, test_command="python -c 'print(\"all good\")'",
        )
        cap = _make_coglet_cap(repo, coglet_id)
        result = cap.run_tests()
        assert isinstance(result, TestResultInfo)
        assert result.passed is True
        assert "all good" in result.output


class TestCogletCapabilityLog:
    def test_get_log_after_propose(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        cap.propose_patch(_simple_diff())
        log = cap.get_log()
        assert len(log) >= 1
        assert log[0].action == "proposed"

    def test_get_log_empty(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        log = cap.get_log()
        assert log == []


class TestCogletCapabilityListPatches:
    def test_list_patches(self, tmp_path):
        repo, coglet_id = _create_test_coglet(tmp_path)
        cap = _make_coglet_cap(repo, coglet_id)
        patch = cap.propose_patch(_simple_diff())
        assert isinstance(patch, PatchResult)
        patches = cap.list_patches()
        assert len(patches) == 1
        assert patches[0].patch_id == patch.patch_id
        assert isinstance(patches[0], PatchSummary)


# ---------------------------------------------------------------------------
# Validation script tests
# ---------------------------------------------------------------------------


class TestValidatePrompt:
    def test_validate_prompt_passes(self, tmp_path):
        from cogos.coglet.validate_prompt import validate
        d = tmp_path / "coglet"
        d.mkdir()
        (d / "main.md").write_text("# Discover\n\n## Process\n1. Do things\n\n```python\nx = 1\n```\n")
        assert validate(str(d)) == []

    def test_validate_prompt_fails_missing_entrypoint(self, tmp_path):
        from cogos.coglet.validate_prompt import validate
        d = tmp_path / "coglet"
        d.mkdir()
        errors = validate(str(d))
        assert any("main.md" in e for e in errors)

    def test_validate_prompt_fails_bad_python(self, tmp_path):
        from cogos.coglet.validate_prompt import validate
        d = tmp_path / "coglet"
        d.mkdir()
        (d / "main.md").write_text("# Test\n\n## Process\n\n```python\ndef broken(\n```\n")
        errors = validate(str(d))
        assert any("syntax" in e.lower() for e in errors)


class TestValidateConfig:
    def test_validate_config_passes(self, tmp_path):
        from cogos.coglet.validate_config import validate
        d = tmp_path / "coglet"
        d.mkdir()
        (d / "criteria.md").write_text("# Criteria\n## Must-Have\n- X\n## Strong Signals\n- Y\n## Red Flags\n- Z\n")
        (d / "rubric.json").write_text('{"github_activity": {"weight": 0.25}}')
        (d / "strategy.md").write_text("# Strategy\nDo stuff here.")
        (d / "diagnosis.md").write_text("# Diagnosis\n## Error Types\nStuff here.")
        sourcer = d / "sourcer"
        sourcer.mkdir()
        for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
            (sourcer / name).write_text(f"# {name}\nSearch for stuff.")
        assert validate(str(d)) == []

    def test_validate_config_fails_bad_json(self, tmp_path):
        from cogos.coglet.validate_config import validate
        d = tmp_path / "coglet"
        d.mkdir()
        (d / "criteria.md").write_text("## Must-Have\n## Strong Signals\n## Red Flags\n")
        (d / "rubric.json").write_text("not json")
        (d / "strategy.md").write_text("ok content here")
        (d / "diagnosis.md").write_text("ok content here")
        sourcer = d / "sourcer"
        sourcer.mkdir()
        for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
            (sourcer / name).write_text("ok content here")
        errors = validate(str(d))
        assert any("rubric.json" in e for e in errors)


class TestCogletCapabilityScope:
    def test_requires_coglet_id(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletCapability(repo, pid)
        # Without scoping, _coglet_id should raise
        with pytest.raises(PermissionError, match="coglet_id"):
            cap.get_status()

    def test_cannot_change_coglet_id(self, tmp_path):
        repo = LocalRepository(str(tmp_path))
        pid = uuid4()
        cap = CogletCapability(repo, pid)
        scoped = cap.scope(coglet_id="abc")
        with pytest.raises(ValueError, match="Cannot change"):
            scoped.scope(coglet_id="xyz")


# ---------------------------------------------------------------------------
# Task 10: Capability registration via image system
# ---------------------------------------------------------------------------


class TestCapabilityRegistration:
    """Test that coglet capabilities can be registered and bound to processes
    through the image system (add_capability + add_process with capability binding)."""

    def test_coglet_capability_registered_and_bound(self, tmp_path):
        """Register a coglets capability and bind it to a process via the image system."""
        from cogos.image.apply import apply_image
        from cogos.image.spec import ImageSpec

        repo = LocalRepository(str(tmp_path))
        spec = ImageSpec(
            capabilities=[
                {
                    "name": "coglets",
                    "handler": "cogos.capabilities.coglet_factory.CogletFactoryCapability",
                    "description": "Coglet factory",
                    "instructions": "",
                    "schema": None,
                    "iam_role_arn": None,
                    "metadata": None,
                },
                {
                    "name": "coglet",
                    "handler": "cogos.capabilities.coglet.CogletCapability",
                    "description": "Single coglet ops",
                    "instructions": "",
                    "schema": None,
                    "iam_role_arn": None,
                    "metadata": None,
                },
            ],
            processes=[
                {
                    "name": "dev-agent",
                    "mode": "daemon",
                    "content": "You are a developer agent.",
                    "runner": "lambda",
                    "executor": "llm",
                    "model": None,
                    "priority": 50.0,
                    "capabilities": ["coglets", "coglet"],
                    "handlers": [],
                    "metadata": {},
                },
            ],
        )
        counts = apply_image(spec, repo)

        assert counts["capabilities"] == 2
        assert counts["processes"] == 1

        # Verify capability objects exist
        caps = repo.list_capabilities()
        cap_names = {c.name for c in caps}
        assert "coglets" in cap_names
        assert "coglet" in cap_names

        # Verify process has both capabilities bound
        procs = repo.list_processes()
        assert len(procs) == 1
        pcs = repo.list_process_capabilities(procs[0].id)
        pc_names = {pc.name for pc in pcs}
        assert "coglets" in pc_names
        assert "coglet" in pc_names


# ---------------------------------------------------------------------------
# Task 11: Full E2E test
# ---------------------------------------------------------------------------


class TestCogletE2E:
    """Full end-to-end: create coglet via image, propose patch, verify, merge."""

    def test_full_workflow(self, tmp_path):
        """
        1. Create coglet (calculator with add function) via image apply
        2. Propose patch (add multiply function + tests)
        3. Verify tests pass on patch
        4. Merge patch
        5. Verify main updated, version bumped, tests pass
        """
        from cogos.coglet import read_file_tree
        from cogos.image.apply import apply_image
        from cogos.image.spec import ImageSpec

        repo = LocalRepository(str(tmp_path))

        # -- Step 1: Create coglet via image system --
        calc_files = {
            "calc.py": "def add(a, b):\n    return a + b\n",
            "test_calc.py": (
                "exec(open('calc.py').read())\n"
                "assert add(2, 3) == 5\n"
                "assert add(-1, 1) == 0\n"
                "print('all tests passed')\n"
            ),
        }
        spec = ImageSpec(
            coglets=[
                {
                    "name": "calculator",
                    "test_command": "python test_calc.py",
                    "files": calc_files,
                    "executor": "subprocess",
                    "timeout_seconds": 30,
                },
            ],
        )
        counts = apply_image(spec, repo)
        assert counts["coglets"] == 1

        # Find the coglet ID
        fs = FileStore(repo)
        coglets_cap = CogletFactoryCapability(repo, uuid4())
        coglet_list = coglets_cap.list()
        assert len(coglet_list) == 1
        coglet_id = coglet_list[0].coglet_id
        assert coglet_list[0].name == "calculator"

        # Verify files were written
        main_files = read_file_tree(fs, coglet_id, "main")
        assert "calc.py" in main_files
        assert "test_calc.py" in main_files

        # -- Step 2: Propose patch (add multiply function + test) --
        cap = _make_coglet_cap(repo, coglet_id)

        diff = (
            "--- a/calc.py\n"
            "+++ b/calc.py\n"
            "@@ -1,2 +1,5 @@\n"
            " def add(a, b):\n"
            "     return a + b\n"
            "+\n"
            "+def multiply(a, b):\n"
            "+    return a * b\n"
            "--- a/test_calc.py\n"
            "+++ b/test_calc.py\n"
            "@@ -1,4 +1,7 @@\n"
            " exec(open('calc.py').read())\n"
            " assert add(2, 3) == 5\n"
            " assert add(-1, 1) == 0\n"
            "+assert multiply(3, 4) == 12\n"
            "+assert multiply(0, 5) == 0\n"
            "+assert multiply(-2, 3) == -6\n"
            " print('all tests passed')\n"
        )

        patch_result = cap.propose_patch(diff)
        assert isinstance(patch_result, PatchResult)

        # -- Step 3: Verify tests pass on the patch --
        assert patch_result.test_passed is True
        assert patch_result.base_version == 0

        # -- Step 4: Merge patch --
        merge_result = cap.merge_patch(patch_result.patch_id)
        assert isinstance(merge_result, MergeResult)
        assert merge_result.merged is True
        assert merge_result.new_version == 1

        # -- Step 5: Verify main updated, version bumped, tests pass --
        main_files_after = read_file_tree(fs, coglet_id, "main")
        assert "def multiply(a, b):" in main_files_after["calc.py"]
        assert "assert multiply(3, 4) == 12" in main_files_after["test_calc.py"]

        # Verify version via status
        status = cap.get_status()
        assert isinstance(status, CogletStatus)
        assert status.version == 1

        # Run tests on updated main
        test_result = cap.run_tests()
        assert isinstance(test_result, TestResultInfo)
        assert test_result.passed is True

    def test_image_coglet_idempotent_update(self, tmp_path):
        """Applying image twice with same coglet name updates rather than duplicates."""
        from cogos.image.apply import apply_image
        from cogos.image.spec import ImageSpec

        repo = LocalRepository(str(tmp_path))

        files_v1 = {"main.py": "v1"}
        spec = ImageSpec(coglets=[{
            "name": "mylib", "test_command": "true",
            "files": files_v1, "executor": "subprocess", "timeout_seconds": 30,
        }])
        apply_image(spec, repo)

        # Apply again with updated files
        files_v2 = {"main.py": "v2", "extra.py": "new"}
        spec2 = ImageSpec(coglets=[{
            "name": "mylib", "test_command": "python -c 'print(1)'",
            "files": files_v2, "executor": "subprocess", "timeout_seconds": 45,
        }])
        counts = apply_image(spec2, repo)
        assert counts["coglets"] == 1

        # Should still have exactly one coglet
        coglets_cap = CogletFactoryCapability(repo, uuid4())
        coglet_list = coglets_cap.list()
        assert len(coglet_list) == 1
        assert coglet_list[0].name == "mylib"

        # Files should be updated
        fs = FileStore(repo)
        from cogos.coglet import read_file_tree
        main_files = read_file_tree(fs, coglet_list[0].coglet_id, "main")
        assert main_files["main.py"] == "v2"
        assert "extra.py" in main_files

        # Meta should be updated
        from cogos.capabilities.coglet_factory import _load_meta
        meta = _load_meta(fs, coglet_list[0].coglet_id)
        assert meta.test_command == "python -c 'print(1)'"
        assert meta.timeout_seconds == 45


# ---------------------------------------------------------------------------
# Runtime fields and run() tests
# ---------------------------------------------------------------------------


class TestCogletMetaRuntimeFields:
    def test_coglet_meta_runtime_fields(self):
        """Verify new runtime fields work when set explicitly."""
        m = CogletMeta(
            name="runner",
            test_command="pytest",
            entrypoint="main.py",
            process_executor="llm",
            model="claude-3",
            capabilities=[{"name": "procs", "alias": "procs"}],
            mode="daemon",
            idle_timeout_ms=5000,
        )
        assert m.entrypoint == "main.py"
        assert m.process_executor == "llm"
        assert m.model == "claude-3"
        assert m.capabilities == [{"name": "procs", "alias": "procs"}]
        assert m.mode == "daemon"
        assert m.idle_timeout_ms == 5000

    def test_coglet_meta_runtime_defaults(self):
        """Verify defaults for data-only coglets (no entrypoint)."""
        m = CogletMeta(name="data-only", test_command="true")
        assert m.entrypoint is None
        assert m.process_executor == "llm"
        assert m.model is None
        assert m.capabilities == []
        assert m.mode == "one_shot"
        assert m.idle_timeout_ms is None


class TestApplyImageCogletRuntimeFields:
    def test_apply_image_coglet_preserves_runtime_fields(self, tmp_path):
        """Create coglet via image spec, verify meta has runtime fields."""
        from cogos.image.apply import apply_image
        from cogos.image.spec import ImageSpec

        repo = LocalRepository(str(tmp_path))
        spec = ImageSpec(coglets=[{
            "name": "mybot",
            "test_command": "true",
            "files": {"main.py": "print('hi')"},
            "entrypoint": "main.py",
            "process_executor": "llm",
            "model": "claude-3",
            "capabilities": [{"name": "procs", "alias": "procs"}],
            "mode": "daemon",
            "idle_timeout_ms": 10000,
        }])
        counts = apply_image(spec, repo)
        assert counts["coglets"] == 1

        # Load the meta and verify runtime fields
        fs = FileStore(repo)
        coglets_cap = CogletFactoryCapability(repo, uuid4())
        coglet_list = coglets_cap.list()
        assert len(coglet_list) == 1
        meta = _load_meta(fs, coglet_list[0].coglet_id)
        assert meta.entrypoint == "main.py"
        assert meta.process_executor == "llm"
        assert meta.model == "claude-3"
        assert meta.capabilities == [{"name": "procs", "alias": "procs"}]
        assert meta.mode == "daemon"
        assert meta.idle_timeout_ms == 10000


class TestCogletRun:
    def _setup_executable_coglet(self, tmp_path):
        """Create a repo with procs capability registered and an executable coglet."""
        from cogos.image.apply import apply_image
        from cogos.image.spec import ImageSpec

        repo = LocalRepository(str(tmp_path))
        # Register procs capability via image
        spec = ImageSpec(capabilities=[
            {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
             "description": "Process management", "instructions": "", "schema": None,
             "iam_role_arn": None, "metadata": None},
        ])
        apply_image(spec, repo)

        # Create a coglet with entrypoint
        fs = FileStore(repo)
        meta = CogletMeta(
            name="my-bot",
            test_command="true",
            entrypoint="main.py",
            process_executor="llm",
            model="claude-3",
            capabilities=["procs"],
            mode="daemon",
            idle_timeout_ms=5000,
        )
        from cogos.coglet import write_file_tree
        write_file_tree(fs, meta.id, "main", {"main.py": "You are a bot."})
        _save_meta(fs, meta)

        return repo, meta.id

    def test_coglet_run_returns_process_handle(self, tmp_path):
        """Create executable coglet, call run(), verify ProcessHandle returned."""
        from cogos.capabilities.process_handle import ProcessHandle
        from cogos.capabilities.procs import ProcsCapability

        repo, coglet_id = self._setup_executable_coglet(tmp_path)

        # Create a parent process that holds the procs capability
        from cogos.db.models import Process, ProcessMode, ProcessStatus
        from cogos.db.models import ProcessCapability as PCModel
        parent = Process(
            name="parent",
            mode=ProcessMode.ONE_SHOT,
            content="parent",
            status=ProcessStatus.RUNNABLE,
        )
        parent_id = repo.upsert_process(parent)

        # Bind procs capability to parent
        procs_cap_db = repo.get_capability_by_name("procs")
        pc = PCModel(process=parent_id, capability=procs_cap_db.id, name="procs")
        repo.create_process_capability(pc)

        # Create procs capability instance
        procs = ProcsCapability(repo, parent_id)

        # Create coglet capability scoped to our coglet
        cap = CogletCapability(repo, parent_id)
        scoped = cap.scope(coglet_id=coglet_id)

        result = scoped.run(procs)
        assert isinstance(result, ProcessHandle), f"Expected ProcessHandle, got {type(result)}: {result}"
        assert result._process.name == "my-bot"
        assert result._process.mode.value == "daemon"
        assert result._process.model == "claude-3"

    def test_coglet_run_fails_without_entrypoint(self, tmp_path):
        """Data-only coglet returns error on run()."""
        repo = LocalRepository(str(tmp_path))
        fs = FileStore(repo)

        # Create a data-only coglet (no entrypoint)
        meta = CogletMeta(
            name="data-only",
            test_command="true",
        )
        from cogos.coglet import write_file_tree
        write_file_tree(fs, meta.id, "main", {"data.txt": "some data"})
        _save_meta(fs, meta)

        cap = CogletCapability(repo, uuid4())
        scoped = cap.scope(coglet_id=meta.id)
        result = scoped.run(None)  # procs not needed since it should fail before spawn
        assert isinstance(result, CogletError)
        assert "no entrypoint" in result.error


# ---------------------------------------------------------------------------
# Task 5: Recruiter coglets created on image apply
# ---------------------------------------------------------------------------


class TestRecruiterCoglets:
    def test_recruiter_cog_created_on_image_apply(self, tmp_path):
        from pathlib import Path

        from cogos.cog import load_cog_meta, load_coglet_meta
        from cogos.image.apply import apply_image
        from cogos.image.spec import load_image

        repo = LocalRepository(str(tmp_path))
        image_dir = Path(__file__).resolve().parents[2] / "images" / "cogent-v1"
        spec = load_image(image_dir)
        apply_image(spec, repo)

        store = FileStore(repo)

        # Cog meta should exist
        cog_meta = load_cog_meta(store, "recruiter")
        assert cog_meta is not None
        assert cog_meta.name == "recruiter"

        # Default coglet should exist
        coglet_meta = load_coglet_meta(store, "recruiter", "recruiter")
        assert coglet_meta is not None
        assert coglet_meta.entrypoint == "recruiter.py"
        assert coglet_meta.mode == "daemon"

        # Process creation is deferred to init.py — verify boot manifest
        raw = store.get_content("_boot/cog_processes.json")
        manifest = json.loads(raw)
        entry = next((e for e in manifest if e["name"] == "recruiter"), None)
        assert entry is not None
