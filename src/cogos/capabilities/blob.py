"""Blob store capability — upload/download files via S3 for cross-capability sharing."""
from __future__ import annotations

import logging
import os
from uuid import uuid4

import boto3
from pydantic import BaseModel, ConfigDict

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

PRESIGNED_URL_EXPIRY = 7 * 24 * 3600  # 7 days


class BlobRef(BaseModel):
    key: str
    url: str
    filename: str
    size: int


class BlobContent(BaseModel):
    data: bytes
    filename: str
    content_type: str | None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class BlobError(BaseModel):
    error: str


class BlobCapability(Capability):
    """Upload and download files via S3 for cross-capability sharing.

    Usage:
        ref = blob.upload(data, "chart.png", content_type="image/png")
        content = blob.download(ref.key)
    """

    ALL_OPS = {"upload", "download"}

    def __init__(self, repo, process_id, run_id=None):
        super().__init__(repo, process_id, run_id)
        from cogos import get_sessions_bucket
        self._bucket = get_sessions_bucket()
        self._s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        e_ops = existing.get("ops")
        r_ops = requested.get("ops")
        if e_ops is not None and r_ops is not None:
            result["ops"] = set(e_ops) & set(r_ops)
        elif e_ops is not None:
            result["ops"] = e_ops
        elif r_ops is not None:
            result["ops"] = r_ops

        e_max = existing.get("max_size_bytes")
        r_max = requested.get("max_size_bytes")
        if e_max is not None and r_max is not None:
            result["max_size_bytes"] = min(e_max, r_max)
        elif e_max is not None:
            result["max_size_bytes"] = e_max
        elif r_max is not None:
            result["max_size_bytes"] = r_max
        return result

    def _check_op(self, op: str) -> str | None:
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            return f"Operation '{op}' not allowed by scope"
        return None

    def upload(self, data: bytes, filename: str, content_type: str | None = None) -> BlobRef | BlobError:
        """Upload bytes to the blob store. Returns a BlobRef with key and presigned URL."""
        err = self._check_op("upload")
        if err:
            return BlobError(error=err)
        if not data:
            return BlobError(error="Cannot upload empty data")
        max_size = self._scope.get("max_size_bytes")
        if max_size is not None and len(data) > max_size:
            return BlobError(error=f"Data size {len(data)} exceeds max size {max_size}")

        key = f"blobs/{uuid4()}/{filename}"
        put_kwargs: dict = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            put_kwargs["ContentType"] = content_type
        try:
            self._s3_client.put_object(**put_kwargs)
            url = self._s3_client.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=PRESIGNED_URL_EXPIRY,
            )
            return BlobRef(key=key, url=url, filename=filename, size=len(data))
        except Exception as e:
            return BlobError(error=str(e))

    def download(self, key: str) -> BlobContent | BlobError:
        """Download a blob by key."""
        err = self._check_op("download")
        if err:
            return BlobError(error=err)
        if not key:
            return BlobError(error="Key is required")
        try:
            resp = self._s3_client.get_object(Bucket=self._bucket, Key=key)
            data = resp["Body"].read()
            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            return BlobContent(data=data, filename=filename, content_type=resp.get("ContentType"))
        except Exception as e:
            return BlobError(error=str(e))

    def __repr__(self) -> str:
        return "<BlobCapability upload() download()>"
