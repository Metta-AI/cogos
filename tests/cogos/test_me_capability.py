"""Tests for the 'me' capability — scoped file/dir access."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock
from uuid import uuid4

import pytest

from cogos.capabilities.me import (
    DirHandle,
    FileHandle,
    MeCapability,
    ProcessScope,
    RunScope,
)


@pytest.fixture()
def mock_repo():
    return MagicMock()


@pytest.fixture()
def mock_store():
    return MagicMock()


@pytest.fixture()
def process_id():
    return uuid4()


@pytest.fixture()
def run_id():
    return uuid4()


# ── FileHandle ───────────────────────────────────────────────


class TestFileHandle:
    def test_read_existing(self, mock_store, mock_repo):
        mock_file = MagicMock()
        mock_file.id = uuid4()
        mock_store.get.return_value = mock_file

        mock_fv = MagicMock()
        mock_fv.content = "hello"
        mock_repo.get_active_file_version.return_value = mock_fv

        fh = FileHandle("/proc/abc/tmp", mock_store, mock_repo)
        assert fh.read() == "hello"
        mock_store.get.assert_called_once_with("/proc/abc/tmp")

    def test_read_missing(self, mock_store, mock_repo):
        mock_store.get.return_value = None
        fh = FileHandle("/proc/abc/tmp", mock_store, mock_repo)
        assert fh.read() is None

    def test_read_no_version(self, mock_store, mock_repo):
        mock_file = MagicMock()
        mock_store.get.return_value = mock_file
        mock_repo.get_active_file_version.return_value = None
        fh = FileHandle("/proc/abc/tmp", mock_store, mock_repo)
        assert fh.read() is None

    def test_write(self, mock_store, mock_repo):
        mock_result = MagicMock()
        mock_result.version = 3
        mock_store.upsert.return_value = mock_result

        fh = FileHandle("/proc/abc/scratch", mock_store, mock_repo)
        result = fh.write("data")

        assert result.key == "/proc/abc/scratch"
        assert result.version == 3
        mock_store.upsert.assert_called_once_with("/proc/abc/scratch", "data", source="process")

    def test_write_none_result(self, mock_store, mock_repo):
        mock_store.upsert.return_value = None
        fh = FileHandle("/proc/abc/scratch", mock_store, mock_repo)
        result = fh.write("data")
        assert result.version == 0

    def test_key_property(self, mock_store, mock_repo):
        fh = FileHandle("/proc/abc/tmp", mock_store, mock_repo)
        assert fh.key == "/proc/abc/tmp"

    def test_repr(self, mock_store, mock_repo):
        fh = FileHandle("/proc/abc/tmp", mock_store, mock_repo)
        assert repr(fh) == "<File /proc/abc/tmp>"


# ── DirHandle ────────────────────────────────────────────────


class TestDirHandle:
    def test_list(self, mock_store, mock_repo):
        f1 = MagicMock()
        f1.key = "/proc/abc/tmp/a"
        f2 = MagicMock()
        f2.key = "/proc/abc/tmp/b"
        mock_store.list_files.return_value = [f1, f2]

        dh = DirHandle("/proc/abc/tmp/", mock_store, mock_repo)
        assert dh.list() == ["/proc/abc/tmp/a", "/proc/abc/tmp/b"]

    def test_read(self, mock_store, mock_repo):
        mock_file = MagicMock()
        mock_file.id = uuid4()
        mock_store.get.return_value = mock_file
        mock_fv = MagicMock()
        mock_fv.content = "contents"
        mock_repo.get_active_file_version.return_value = mock_fv

        dh = DirHandle("/proc/abc/tmp/", mock_store, mock_repo)
        assert dh.read("foo") == "contents"
        mock_store.get.assert_called_with("/proc/abc/tmp/foo")

    def test_write(self, mock_store, mock_repo):
        mock_result = MagicMock()
        mock_result.version = 1
        mock_store.upsert.return_value = mock_result

        dh = DirHandle("/proc/abc/tmp/", mock_store, mock_repo)
        result = dh.write("foo", "bar")
        assert result.key == "/proc/abc/tmp/foo"
        mock_store.upsert.assert_called_with("/proc/abc/tmp/foo", "bar", source="process")

    def test_file(self, mock_store, mock_repo):
        dh = DirHandle("/proc/abc/tmp/", mock_store, mock_repo)
        fh = dh.file("x")
        assert isinstance(fh, FileHandle)
        assert fh.key == "/proc/abc/tmp/x"


# ── RunScope / ProcessScope ──────────────────────────────────


class TestRunScope:
    def test_paths(self, mock_store, mock_repo, process_id, run_id):
        scope = RunScope(process_id, run_id, mock_store, mock_repo)
        base = f"/proc/{process_id}/runs/{run_id}"

        assert scope.tmp().key == f"{base}/tmp"
        assert scope.tmp_dir().key == f"{base}/tmp/"
        assert scope.log().key == f"{base}/log"
        assert scope.scratch().key == f"{base}/scratch"
        assert scope.scratch_dir().key == f"{base}/scratch/"

    def test_repr(self, mock_store, mock_repo, process_id, run_id):
        scope = RunScope(process_id, run_id, mock_store, mock_repo)
        assert "RunScope" in repr(scope)


class TestProcessScope:
    def test_paths(self, mock_store, mock_repo, process_id):
        scope = ProcessScope(process_id, mock_store, mock_repo)
        base = f"/proc/{process_id}"

        assert scope.tmp().key == f"{base}/tmp"
        assert scope.tmp_dir().key == f"{base}/tmp/"
        assert scope.log().key == f"{base}/log"
        assert scope.scratch().key == f"{base}/scratch"
        assert scope.scratch_dir().key == f"{base}/scratch/"


# ── MeCapability ─────────────────────────────────────────────


class TestMeCapability:
    def test_process_scope(self, mock_repo, process_id, run_id):
        me = MeCapability(mock_repo, process_id, run_id=run_id)
        scope = me.process()
        assert isinstance(scope, ProcessScope)
        assert f"/proc/{process_id}" in repr(scope)

    def test_run_scope(self, mock_repo, process_id, run_id):
        me = MeCapability(mock_repo, process_id, run_id=run_id)
        scope = me.run()
        assert isinstance(scope, RunScope)
        assert str(run_id) in repr(scope)

    def test_run_without_run_id_raises(self, mock_repo, process_id):
        me = MeCapability(mock_repo, process_id, run_id=None)
        with pytest.raises(RuntimeError, match="No active run"):
            me.run()

    def test_repr(self, mock_repo, process_id, run_id):
        me = MeCapability(mock_repo, process_id, run_id=run_id)
        r = repr(me)
        assert "MeCapability" in r
        assert str(process_id) in r
