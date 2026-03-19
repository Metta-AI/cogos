"""Tests for image compositing functions — overlay_text, watermark, combine."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef
from cogos.capabilities.image import ImageCapability, ImageError


def _make_png(width: int, height: int, color: str = "red") -> bytes:
    """Create a PNG image of given size and color, return as bytes."""
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_cap(scope: dict | None = None) -> ImageCapability:
    """Create an ImageCapability with mocked internals."""
    repo = MagicMock()
    with patch("cogos.capabilities.image.BlobCapability"):
        cap = ImageCapability(repo, uuid4())
    if scope is not None:
        cap._scope = scope
    return cap


def _patch_blob(cap: ImageCapability, key_to_bytes: dict[str, bytes]) -> BlobRef:
    """Mock blob download (key→bytes map) and upload (returns a BlobRef)."""
    uploaded_ref = BlobRef(key="blobs/out/result.png", url="https://s3/result.png", filename="result.png", size=999)

    def _download_side(key: str):
        if key in key_to_bytes:
            return BlobContent(data=key_to_bytes[key], filename=key.split("/")[-1], content_type="image/png")
        from cogos.capabilities.blob import BlobError

        return BlobError(error=f"Not found: {key}")

    cap._blob.download = MagicMock(side_effect=_download_side)
    cap._blob.upload = MagicMock(return_value=uploaded_ref)
    return uploaded_ref


# ── overlay_text tests ──────────────────────────────────────


def test_overlay_text_returns_blobref():
    cap = _make_cap()
    png_data = _make_png(100, 100)
    expected_ref = _patch_blob(cap, {"img/test.png": png_data})

    result = cap.overlay_text("img/test.png", "Hello World", position="center")

    assert isinstance(result, BlobRef)
    assert result.key == expected_ref.key
    cap._blob.upload.assert_called_once()  # type: ignore[attr-defined]


def test_overlay_text_scope_denied():
    cap = _make_cap(scope={"ops": ["resize"]})
    png_data = _make_png(100, 100)
    _patch_blob(cap, {"img/test.png": png_data})

    result = cap.overlay_text("img/test.png", "Hello")

    assert isinstance(result, ImageError)
    assert "not allowed" in result.error


# ── watermark tests ─────────────────────────────────────────


def test_watermark_returns_blobref():
    cap = _make_cap()
    base_data = _make_png(200, 200, "blue")
    wm_data = _make_png(50, 50, "white")
    expected_ref = _patch_blob(cap, {"img/base.png": base_data, "img/wm.png": wm_data})

    result = cap.watermark("img/base.png", "img/wm.png", position="bottom-right", opacity=0.5)

    assert isinstance(result, BlobRef)
    assert result.key == expected_ref.key
    cap._blob.upload.assert_called_once()  # type: ignore[attr-defined]


# ── combine tests ───────────────────────────────────────────


def test_combine_horizontal():
    cap = _make_cap()
    img1_data = _make_png(50, 80, "red")
    img2_data = _make_png(60, 80, "green")
    _patch_blob(cap, {"img/a.png": img1_data, "img/b.png": img2_data})

    result = cap.combine(["img/a.png", "img/b.png"], layout="horizontal")

    assert isinstance(result, BlobRef)
    # Verify the uploaded image dimensions
    call_args = cap._blob.upload.call_args  # type: ignore[attr-defined]
    uploaded_bytes = call_args[0][0] if call_args[0] else call_args.kwargs.get("data")
    combined = Image.open(io.BytesIO(uploaded_bytes))
    assert combined.size == (110, 80)


def test_combine_vertical():
    cap = _make_cap()
    img1_data = _make_png(80, 50, "red")
    img2_data = _make_png(80, 60, "green")
    _patch_blob(cap, {"img/a.png": img1_data, "img/b.png": img2_data})

    result = cap.combine(["img/a.png", "img/b.png"], layout="vertical")

    assert isinstance(result, BlobRef)
    call_args = cap._blob.upload.call_args  # type: ignore[attr-defined]
    uploaded_bytes = call_args[0][0] if call_args[0] else call_args.kwargs.get("data")
    combined = Image.open(io.BytesIO(uploaded_bytes))
    assert combined.size == (80, 110)
