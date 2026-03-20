"""Tests for BlobCapability."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.blob import BlobCapability, BlobRef, BlobContent, BlobError


def _make_cap():
    repo = MagicMock()
    runtime = MagicMock()
    cap = BlobCapability(repo, uuid4(), runtime=runtime)
    cap._cogent_name = "test-cogent"
    return cap


def test_upload_returns_blob_ref():
    cap = _make_cap()
    cap._runtime.get_file_url.return_value = "https://s3.../presigned"
    result = cap.upload(b"hello world", "test.txt", content_type="text/plain")
    assert isinstance(result, BlobRef)
    assert result.filename == "test.txt"
    assert result.size == 11
    assert result.url == "https://s3.../presigned"
    assert result.key.startswith("blobs/")
    assert result.key.endswith("/test.txt")
    cap._runtime.put_file.assert_called_once()
    call_args = cap._runtime.put_file.call_args
    assert call_args[0][0] == "test-cogent"
    assert call_args[0][2] == b"hello world"


def test_upload_empty_data():
    cap = _make_cap()
    result = cap.upload(b"", "empty.txt")
    assert isinstance(result, BlobError)
    assert "empty" in result.error.lower()


def test_download_returns_content():
    cap = _make_cap()
    cap._runtime.get_file.return_value = b"file data"
    result = cap.download("blobs/abc/test.txt")
    assert isinstance(result, BlobContent)
    assert result.data == b"file data"
    assert result.filename == "test.txt"


def test_download_invalid_key():
    cap = _make_cap()
    result = cap.download("")
    assert isinstance(result, BlobError)


def test_upload_scope_max_size():
    cap = _make_cap()
    scoped = cap.scope(max_size_bytes=10)
    result = scoped.upload(b"x" * 100, "big.bin")
    assert isinstance(result, BlobError)
    assert "size" in result.error.lower()


def test_upload_scope_ops_blocked():
    cap = _make_cap()
    scoped = cap.scope(ops=["download"])
    result = scoped.upload(b"data", "test.txt")
    assert isinstance(result, BlobError)


def test_download_scope_ops_blocked():
    cap = _make_cap()
    scoped = cap.scope(ops=["upload"])
    result = scoped.download("blobs/abc/test.txt")
    assert isinstance(result, BlobError)


def test_cogent_name_from_env(monkeypatch):
    """When COGENT_NAME is set, use it."""
    monkeypatch.setenv("COGENT_NAME", "dr.alpha")
    repo = MagicMock()
    runtime = MagicMock()
    cap = BlobCapability(repo, uuid4(), runtime=runtime)
    assert cap._cogent_name == "dr.alpha"


def test_no_runtime_returns_error():
    """When no runtime is available, operations return errors."""
    repo = MagicMock()
    cap = BlobCapability(repo, uuid4())
    result = cap.upload(b"data", "test.txt")
    assert isinstance(result, BlobError)
    assert "runtime" in result.error.lower()
