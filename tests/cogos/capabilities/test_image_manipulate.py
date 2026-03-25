"""Tests for image manipulation operations."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef
from cogos.capabilities.image import ImageCapability, ImageError


def _make_png(width: int = 100, height: int = 80, mode: str = "RGBA", color=(255, 0, 0, 255)) -> bytes:
    """Create a test PNG image and return its bytes."""
    img = Image.new(mode, (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_cap() -> ImageCapability:
    """Create an ImageCapability with mocked blob backend."""
    repo = MagicMock()
    with patch("cogos.capabilities.image.BlobCapability"):
        cap = ImageCapability(repo, uuid4())
    return cap


def _setup_mocks(cap: ImageCapability, png_bytes: bytes, filename: str = "test.png"):
    """Wire up download/upload mocks on the capability's blob sub-capability."""
    cap._blob.download = MagicMock(return_value=BlobContent(
        data=png_bytes, filename=filename, content_type="image/png",
    ))
    uploaded = {}

    def fake_upload(data, fname, content_type=None):
        uploaded["data"] = data
        uploaded["filename"] = fname
        return BlobRef(key=f"blobs/{uuid4()}/{fname}", url="https://s3.../presigned", filename=fname, size=len(data))

    cap._blob.upload = MagicMock(side_effect=fake_upload)
    return uploaded


def _read_uploaded_image(uploaded: dict) -> Image.Image:
    """Read a PIL Image from the uploaded bytes stored by the fake_upload mock."""
    return Image.open(io.BytesIO(uploaded["data"]))


# -- resize --

def test_resize_both_dims():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.resize("blobs/abc/test.png", width=50, height=40)
    assert isinstance(result, BlobRef)
    img = _read_uploaded_image(uploaded)
    assert img.size == (50, 40)


def test_resize_width_only():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.resize("blobs/abc/test.png", width=50)
    assert isinstance(result, BlobRef)
    img = _read_uploaded_image(uploaded)
    assert img.size == (50, 40)  # aspect preserved: 80 * (50/100) = 40


def test_resize_height_only():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.resize("blobs/abc/test.png", height=40)
    assert isinstance(result, BlobRef)
    img = _read_uploaded_image(uploaded)
    assert img.size == (50, 40)  # aspect preserved: 100 * (40/80) = 50


def test_resize_no_dims_error():
    cap = _make_cap()
    png = _make_png()
    _setup_mocks(cap, png)

    result = cap.resize("blobs/abc/test.png")
    assert isinstance(result, ImageError)
    assert "width" in result.error.lower() or "height" in result.error.lower()


# -- crop --

def test_crop():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.crop("blobs/abc/test.png", left=10, top=10, right=60, bottom=50)
    assert isinstance(result, BlobRef)
    img = _read_uploaded_image(uploaded)
    assert img.size == (50, 40)


# -- rotate --

def test_rotate_90():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.rotate("blobs/abc/test.png", degrees=90)
    assert isinstance(result, BlobRef)
    img = _read_uploaded_image(uploaded)
    # 90-degree rotation with expand=True swaps dimensions
    assert img.size == (80, 100)


# -- convert --

def test_convert_to_jpeg():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.convert("blobs/abc/test.png", format="JPEG")
    assert isinstance(result, BlobRef)
    assert result.filename.endswith(".jpg")
    img = _read_uploaded_image(uploaded)
    assert img.size == (100, 80)
    assert img.mode == "RGB"  # JPEG converts to RGB


# -- thumbnail --

def test_thumbnail():
    cap = _make_cap()
    png = _make_png(100, 80)
    uploaded = _setup_mocks(cap, png)

    result = cap.thumbnail("blobs/abc/test.png", max_size=50)
    assert isinstance(result, BlobRef)
    img = _read_uploaded_image(uploaded)
    w, h = img.size
    assert w <= 50 and h <= 50
    # Should preserve aspect ratio: 100x80 → 50x40
    assert img.size == (50, 40)


# -- scope denial --

def test_scope_denial():
    cap = _make_cap()
    png = _make_png()
    _setup_mocks(cap, png)

    cap._scope = {"ops": ["crop"]}
    result = cap.resize("blobs/abc/test.png", width=50)
    assert isinstance(result, ImageError)
    assert "not allowed" in result.error.lower()
