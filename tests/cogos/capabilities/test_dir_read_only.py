"""Tests for DirCapability read_only scope."""
import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.file_cap import DirCapability, FileCapability


def _make_dir_cap(prefix="test/", read_only=False):
    repo = MagicMock()
    cap = DirCapability(repo=repo, process_id=uuid4())
    scope = {"prefix": prefix}
    if read_only:
        scope["read_only"] = True
    cap._scope = scope
    return cap


def test_read_only_get_returns_read_only_file():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    fc = d.get("foo.txt")
    assert fc._scope["ops"] == {"read"}


def test_writable_get_returns_writable_file():
    d = _make_dir_cap(prefix="mnt/disk/myapp/", read_only=False)
    fc = d.get("foo.txt")
    assert "ops" not in fc._scope


def test_read_only_cannot_be_widened():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    child = d.scope(prefix="mnt/boot/sub/")
    assert child._scope.get("read_only") is True


def test_read_only_can_be_narrowed_from_writable():
    d = _make_dir_cap(prefix="mnt/disk/", read_only=False)
    child = d.scope(prefix="mnt/disk/sub/", read_only=True)
    assert child._scope.get("read_only") is True


def test_read_only_file_write_raises():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    fc = d.get("foo.txt")
    with pytest.raises(PermissionError, match="not permitted"):
        fc.write("hello")


def test_read_only_file_read_allowed():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    fc = d.get("foo.txt")
    # _check("read") should not raise with ops={"read"}
    fc._check("read", key="mnt/boot/foo.txt")


def test_repr_shows_read_only():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    assert "read-only" in repr(d)
