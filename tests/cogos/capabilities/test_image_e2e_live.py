"""End-to-end live test for image capability — generate, manipulate, analyze.

Requires GOOGLE_API_KEY env var. Skip with: pytest -m "not live"
"""
from __future__ import annotations

import io
import os
from unittest.mock import MagicMock

import pytest
from PIL import Image

from cogos.capabilities.blob import BlobCapability, BlobContent, BlobRef, BlobError
from cogos.capabilities.image import ImageCapability, ImageDescription, AnalysisResult, ExtractedText, ImageError


pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set — skipping live Gemini tests",
)


# ── In-memory blob store (no S3 needed) ─────────────────────

class InMemoryBlobStore:
    """Fake blob store backed by a dict."""

    def __init__(self):
        self._store: dict[str, bytes] = {}
        self._counter = 0

    def upload(self, data: bytes, filename: str, content_type: str | None = None) -> BlobRef:
        self._counter += 1
        key = f"blobs/test/{self._counter}/{filename}"
        self._store[key] = data
        return BlobRef(key=key, url=f"mem://{key}", filename=filename, size=len(data))

    def download(self, key: str) -> BlobContent | BlobError:
        data = self._store.get(key)
        if data is None:
            return BlobError(error=f"Key not found: {key}")
        filename = key.rsplit("/", 1)[-1]
        return BlobContent(data=data, filename=filename, content_type="image/png")


def _make_live_capability() -> ImageCapability:
    """Create an ImageCapability with in-memory blob store and real Gemini."""
    repo = MagicMock()
    cap = ImageCapability(repo, process_id=MagicMock())
    cap._blob = InMemoryBlobStore()
    return cap


def _get_image(cap: ImageCapability, ref: BlobRef) -> Image.Image:
    """Download a blob ref and return as PIL Image."""
    content = cap._blob.download(ref.key)
    assert not isinstance(content, BlobError), f"Download failed: {content.error}"
    return Image.open(io.BytesIO(content.data))


# ── Tests ────────────────────────────────────────────────────

class TestGenerateManipulateAnalyze:
    """Full pipeline: generate → manipulate → analyze."""

    def test_generate_image(self):
        """Generate an image from a text prompt."""
        cap = _make_live_capability()
        result = cap.generate("a bright red apple on a white background, simple illustration")
        assert isinstance(result, BlobRef), f"Generate failed: {result}"
        img = _get_image(cap, result)
        assert img.size[0] > 0 and img.size[1] > 0
        print(f"  Generated image: {img.size[0]}x{img.size[1]}")

    def test_generate_then_resize(self):
        """Generate an image, then resize it."""
        cap = _make_live_capability()
        ref = cap.generate("a blue circle on white background")
        assert isinstance(ref, BlobRef), f"Generate failed: {ref}"

        resized = cap.resize(ref.key, width=200)
        assert isinstance(resized, BlobRef), f"Resize failed: {resized}"
        img = _get_image(cap, resized)
        assert img.size[0] == 200
        print(f"  Resized to: {img.size[0]}x{img.size[1]}")

    def test_generate_then_describe(self):
        """Generate an image, then describe it with Gemini Vision."""
        cap = _make_live_capability()
        ref = cap.generate("a yellow sunflower in a green field")
        assert isinstance(ref, BlobRef), f"Generate failed: {ref}"

        desc = cap.describe(ref.key)
        assert isinstance(desc, ImageDescription), f"Describe failed: {desc}"
        assert len(desc.description) > 10
        print(f"  Description: {desc.description[:200]}")

    def test_generate_then_analyze(self):
        """Generate an image, then ask a question about it."""
        cap = _make_live_capability()
        ref = cap.generate("a red triangle and a blue square on white background")
        assert isinstance(ref, BlobRef), f"Generate failed: {ref}"

        result = cap.analyze(ref.key, "How many shapes are in this image and what colors are they?")
        assert isinstance(result, AnalysisResult), f"Analyze failed: {result}"
        assert len(result.answer) > 5
        print(f"  Analysis: {result.answer[:200]}")

    def test_full_pipeline(self):
        """Generate → resize → overlay text → describe."""
        cap = _make_live_capability()

        # Generate
        ref = cap.generate("a mountain landscape at sunset")
        assert isinstance(ref, BlobRef), f"Generate failed: {ref}"
        print(f"  1. Generated: {ref.key}")

        # Resize
        ref2 = cap.resize(ref.key, width=512)
        assert isinstance(ref2, BlobRef), f"Resize failed: {ref2}"
        img = _get_image(cap, ref2)
        print(f"  2. Resized to: {img.size[0]}x{img.size[1]}")

        # Overlay text
        ref3 = cap.overlay_text(ref2.key, "Beautiful Sunset", position="bottom", font_size=20)
        assert isinstance(ref3, BlobRef), f"Overlay failed: {ref3}"
        print(f"  3. Added text overlay")

        # Describe the final result
        desc = cap.describe(ref3.key)
        assert isinstance(desc, ImageDescription), f"Describe failed: {desc}"
        print(f"  4. Description: {desc.description[:200]}")

    def test_edit_image(self):
        """Generate an image, then edit it."""
        cap = _make_live_capability()
        ref = cap.generate("a simple house drawing")
        assert isinstance(ref, BlobRef), f"Generate failed: {ref}"

        edited = cap.edit(ref.key, "add a tree next to the house")
        assert isinstance(edited, BlobRef), f"Edit failed: {edited}"
        img = _get_image(cap, edited)
        assert img.size[0] > 0
        print(f"  Edited image: {img.size[0]}x{img.size[1]}")
