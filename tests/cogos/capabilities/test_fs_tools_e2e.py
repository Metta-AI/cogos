"""End-to-end tests for fs-tools: grep, glob, tree, sliced read, edit.

Uses SqliteRepository with real file operations — no mocking.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from cogos.capabilities.file_cap import DirCapability, FileCapability
from cogos.capabilities.files import FileContent, FileError
from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(str(tmp_path))


@pytest.fixture
def fs(repo):
    return FileStore(repo)


@pytest.fixture
def pid():
    return uuid4()


@pytest.fixture
def populated_repo(repo, fs):
    """Create a repo with several files for search/navigation tests."""
    fs.create(
        "src/main.py",
        "import os\nimport sys\n\ndef main():\n    print('hello')\n    # TODO: add logging\n    return 0\n",
    )
    fs.create("src/utils.py", "def helper():\n    # TODO: refactor this\n    return 42\n\ndef unused():\n    pass\n")
    fs.create("src/config.yaml", "debug: true\nport: 8080\n")
    fs.create("docs/readme.md", "# My Project\n\nA sample project.\n")
    fs.create("docs/api.md", "# API Reference\n\n## Endpoints\n\nGET /health\nPOST /data\n")
    fs.create(
        "src/big_file.py",
        "\n".join(f"line_{i} = {i}" for i in range(200)),
    )
    return repo


# ── dir.grep ──────────────────────────────────────────────


class TestDirGrep:
    def test_grep_finds_pattern_across_files(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep("TODO")
        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"src/main.py", "src/utils.py"}

    def test_grep_returns_correct_line_numbers(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep("TODO")
        main_result = next(r for r in results if r.key == "src/main.py")
        assert main_result.matches[0].line == 5
        assert "TODO" in main_result.matches[0].text

    def test_grep_with_prefix_narrows_search(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep("TODO", prefix="src/utils")
        assert len(results) == 1
        assert results[0].key == "src/utils.py"

    def test_grep_with_context(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep("TODO", prefix="src/main", context=1)
        m = results[0].matches[0]
        assert len(m.before) == 1
        assert len(m.after) == 1

    def test_grep_respects_limit(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep("TODO", limit=1)
        total_matches = sum(len(r.matches) for r in results)
        assert total_matches == 1

    def test_grep_no_matches(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep("NONEXISTENT_STRING_XYZ")
        assert results == []

    def test_grep_regex_pattern(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.grep(r"def \w+\(\)")
        assert len(results) >= 1

    def test_grep_scoped_prefix(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        scoped = cap.scope(prefix="docs/")
        results = scoped.grep("API")
        assert len(results) == 1
        assert results[0].key == "docs/api.md"

    def test_grep_denied_by_scope(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        scoped = cap.scope(ops={"list", "get"})
        with pytest.raises(PermissionError):
            scoped.grep("TODO")


# ── dir.glob ──────────────────────────────────────────────


class TestDirGlob:
    def test_glob_star(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.glob("src/*.py")
        keys = {r.key for r in results}
        assert "src/main.py" in keys
        assert "src/utils.py" in keys
        assert "src/big_file.py" in keys
        assert "src/config.yaml" not in keys

    def test_glob_double_star(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.glob("**/*.md")
        keys = {r.key for r in results}
        assert "docs/readme.md" in keys
        assert "docs/api.md" in keys

    def test_glob_question_mark(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.glob("docs/???.md")
        keys = {r.key for r in results}
        assert "docs/api.md" in keys
        assert "docs/readme.md" not in keys  # "readme" is 6 chars

    def test_glob_no_matches(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        results = cap.glob("nonexistent/**")
        assert results == []

    def test_glob_scoped_prefix(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        scoped = cap.scope(prefix="src/")
        results = scoped.glob("src/*.yaml")
        keys = {r.key for r in results}
        assert "src/config.yaml" in keys

    def test_glob_denied_by_scope(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        scoped = cap.scope(ops={"list", "get"})
        with pytest.raises(PermissionError):
            scoped.glob("*.py")


# ── dir.tree ──────────────────────────────────────────────


class TestDirTree:
    def test_tree_shows_structure(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        output = cap.tree()
        assert "src/" in output
        assert "docs/" in output
        assert "main.py" in output

    def test_tree_with_prefix(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        scoped = cap.scope(prefix="src/")
        output = scoped.tree()
        assert "main.py" in output
        assert "docs/" not in output

    def test_tree_depth_limit(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        output = cap.tree(depth=1)
        # At depth=1, should show top-level entries but no nested files
        assert "src" in output
        assert "docs" in output
        assert "main.py" not in output

    def test_tree_denied_by_scope(self, populated_repo, pid):
        cap = DirCapability(populated_repo, pid)
        scoped = cap.scope(ops={"list", "get"})
        with pytest.raises(PermissionError):
            scoped.tree()


# ── file.read (sliced) ───────────────────────────────────


class TestFileSlicedReadE2E:
    def test_full_read_includes_total_lines(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.read("src/big_file.py")
        assert isinstance(result, FileContent)
        assert result.total_lines == 200

    def test_offset_limit(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.read("src/big_file.py", offset=10, limit=5)
        assert not isinstance(result, FileError)
        assert result.total_lines == 200
        lines = result.content.split("\n")
        assert len(lines) == 5
        assert lines[0] == "line_10 = 10"
        assert lines[4] == "line_14 = 14"

    def test_head(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.head("src/big_file.py", n=3)
        assert not isinstance(result, FileError)
        lines = result.content.split("\n")
        assert len(lines) == 3
        assert lines[0] == "line_0 = 0"

    def test_tail(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.tail("src/big_file.py", n=3)
        assert not isinstance(result, FileError)
        lines = result.content.split("\n")
        assert len(lines) == 3
        assert lines[-1] == "line_199 = 199"

    def test_negative_offset(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.read("src/big_file.py", offset=-5)
        assert not isinstance(result, FileError)
        lines = result.content.split("\n")
        assert len(lines) == 5
        assert lines[-1] == "line_199 = 199"

    def test_read_via_dir_get(self, populated_repo, pid):
        """Test sliced read through dir.get() flow."""
        dir_cap = DirCapability(populated_repo, pid)
        scoped = dir_cap.scope(prefix="src/")
        f = scoped.get("big_file.py")
        result = f.read(offset=0, limit=2)
        assert not isinstance(result, FileError)
        assert result.total_lines == 200
        assert result.content == "line_0 = 0\nline_1 = 1"


# ── file.edit ─────────────────────────────────────────────


class TestFileEditE2E:
    def test_edit_unique_match(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.edit("src/config.yaml", old="debug: true", new="debug: false")
        assert not isinstance(result, FileError)
        # Verify the edit persisted
        content = cap.read("src/config.yaml")
        assert not isinstance(content, FileError)
        assert "debug: false" in content.content
        assert "debug: true" not in content.content

    def test_edit_replace_all(self, populated_repo, pid, fs):
        fs.create("test/repeated.txt", "aaa\nbbb\naaa\nccc\naaa")
        cap = FileCapability(populated_repo, pid)
        result = cap.edit("test/repeated.txt", old="aaa", new="xxx", replace_all=True)
        assert not isinstance(result, FileError)
        content = cap.read("test/repeated.txt")
        assert not isinstance(content, FileError)
        assert content.content == "xxx\nbbb\nxxx\nccc\nxxx"

    def test_edit_fails_not_unique(self, populated_repo, pid, fs):
        fs.create("test/dup.txt", "aaa\naaa\nbbb")
        cap = FileCapability(populated_repo, pid)
        result = cap.edit("test/dup.txt", old="aaa", new="xxx")
        assert isinstance(result, FileError)
        assert "not unique" in result.error

    def test_edit_fails_not_found(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        result = cap.edit("src/config.yaml", old="nonexistent", new="xxx")
        assert isinstance(result, FileError)
        assert "not found" in result.error

    def test_edit_via_dir_get(self, populated_repo, pid):
        """Test edit through dir.get() flow."""
        dir_cap = DirCapability(populated_repo, pid)
        f = dir_cap.get("src/config.yaml")
        result = f.edit(old="port: 8080", new="port: 9090")
        assert not isinstance(result, FileError)
        content = f.read()
        assert not isinstance(content, FileError)
        assert "port: 9090" in content.content

    def test_edit_denied_by_scope(self, populated_repo, pid):
        cap = FileCapability(populated_repo, pid)
        scoped = cap.scope(key="src/config.yaml", ops={"read"})
        with pytest.raises(PermissionError):
            scoped.edit(old="debug: true", new="debug: false")


# ── Combined workflow ─────────────────────────────────────


class TestFullWorkflow:
    def test_grep_then_edit(self, populated_repo, pid):
        """Simulate: find TODOs, then edit them out."""
        dir_cap = DirCapability(populated_repo, pid)

        # Find all TODOs
        results = dir_cap.grep("TODO")
        assert len(results) == 2

        # Edit each one
        for r in results:
            f = dir_cap.get(r.key)
            for m in r.matches:
                f.edit(old=m.text, new=m.text.replace("TODO", "DONE"))

        # Verify no TODOs remain
        results = dir_cap.grep("TODO")
        assert results == []

        # Verify DONEs exist
        results = dir_cap.grep("DONE")
        assert len(results) == 2

    def test_tree_then_glob_then_read(self, populated_repo, pid):
        """Simulate: orient with tree, find files, read slices."""
        dir_cap = DirCapability(populated_repo, pid)

        # Orient
        tree = dir_cap.tree()
        assert "src/" in tree

        # Find all Python files
        py_files = dir_cap.glob("**/*.py")
        assert len(py_files) >= 3

        # Read head of each
        for entry in py_files:
            f = dir_cap.get(entry.key)
            head = f.head(n=2)
            assert isinstance(head, FileContent)
            assert head.total_lines is not None
