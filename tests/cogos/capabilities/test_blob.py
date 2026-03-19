"""Tests for BlobCapability."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.blob import BlobCapability, BlobRef, BlobContent, BlobError


def _make_cap(bucket="test-bucket"):
    repo = MagicMock()
    cap = BlobCapability(repo, uuid4())
    cap._bucket = bucket
    cap._s3_client = MagicMock()
    return cap


def test_upload_returns_blob_ref():
    cap = _make_cap()
    cap._s3_client.generate_presigned_url.return_value = "https://s3.../presigned"
    result = cap.upload(b"hello world", "test.txt", content_type="text/plain")
    assert isinstance(result, BlobRef)
    assert result.filename == "test.txt"
    assert result.size == 11
    assert result.url == "https://s3.../presigned"
    assert result.key.startswith("blobs/")
    assert result.key.endswith("/test.txt")
    cap._s3_client.put_object.assert_called_once()
    call_kwargs = cap._s3_client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "test-bucket"
    assert call_kwargs["Body"] == b"hello world"
    assert call_kwargs["ContentType"] == "text/plain"


def test_upload_empty_data():
    cap = _make_cap()
    result = cap.upload(b"", "empty.txt")
    assert isinstance(result, BlobError)
    assert "empty" in result.error.lower()


def test_download_returns_content():
    cap = _make_cap()
    body_mock = MagicMock()
    body_mock.read.return_value = b"file data"
    cap._s3_client.get_object.return_value = {"Body": body_mock, "ContentType": "text/plain"}
    result = cap.download("blobs/abc/test.txt")
    assert isinstance(result, BlobContent)
    assert result.data == b"file data"
    assert result.filename == "test.txt"
    assert result.content_type == "text/plain"


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


def test_bucket_derived_from_cogent_name(monkeypatch):
    """When SESSIONS_BUCKET is unset, derive bucket from COGENT_NAME."""
    monkeypatch.delenv("SESSIONS_BUCKET", raising=False)
    monkeypatch.setenv("COGENT_NAME", "dr.alpha")
    repo = MagicMock()
    cap = BlobCapability(repo, uuid4())
    assert cap._bucket == "cogent-dr-alpha-cogtainer-sessions"


def test_bucket_from_env(monkeypatch):
    """When SESSIONS_BUCKET is set, use it directly."""
    monkeypatch.setenv("SESSIONS_BUCKET", "my-custom-bucket")
    repo = MagicMock()
    cap = BlobCapability(repo, uuid4())
    assert cap._bucket == "my-custom-bucket"
