"""Image capability — manipulation, compositing, AI analysis, and generation."""
from __future__ import annotations

import io
import logging
from typing import Any

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.blob import BlobCapability, BlobError, BlobRef

logger = logging.getLogger(__name__)

ALL_OPS = {
    "resize", "crop", "rotate", "convert", "thumbnail",
    "overlay_text", "watermark", "combine",
    "describe", "analyze", "extract_text",
    "generate", "edit", "variations",
}


# ── IO Models ────────────────────────────────────────────────

class ImageDescription(BaseModel):
    key: str
    description: str

class AnalysisResult(BaseModel):
    key: str
    answer: str

class ExtractedText(BaseModel):
    key: str
    text: str

class ImageError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────

class ImageCapability(Capability):
    """Manipulate, compose, analyze, and generate images.

    All operations are blob-key oriented: input blob keys, output new blob keys.

    Usage:
        ref = image.generate("a sunset over mountains")
        ref2 = image.resize(ref.key, width=800)
        ref3 = image.overlay_text(ref2.key, "Hello!", position="bottom")
    """

    def __init__(self, repo, process_id, run_id=None, trace_id=None, **kwargs):
        super().__init__(repo, process_id, run_id, trace_id, **kwargs)
        self._blob = BlobCapability(repo, process_id, run_id)

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        e_ops = existing.get("ops")
        r_ops = requested.get("ops")
        if e_ops is not None and r_ops is not None:
            result["ops"] = sorted(set(e_ops) & set(r_ops))
        elif e_ops is not None:
            result["ops"] = e_ops
        elif r_ops is not None:
            result["ops"] = r_ops
        return result

    def _check_op(self, op: str) -> str | None:
        allowed = self._scope.get("ops")
        if allowed is not None and op not in allowed:
            return f"Operation '{op}' not allowed by scope"
        return None

    def _download_image(self, key: str):
        """Download a blob and return a PIL Image."""
        from PIL import Image
        content = self._blob.download(key)
        if isinstance(content, BlobError):
            return None, content.error
        return Image.open(io.BytesIO(content.data)), None

    def _upload_image(self, img, filename: str, fmt: str = "PNG") -> BlobRef | ImageError:
        """Save a PIL Image to blob store."""
        buf = io.BytesIO()
        save_kwargs: dict[str, Any] = {}
        if fmt.upper() == "JPEG":
            img = img.convert("RGB")
            save_kwargs["quality"] = 95
        img.save(buf, format=fmt, **save_kwargs)
        data = buf.getvalue()
        content_type = f"image/{fmt.lower()}"
        result = self._blob.upload(data, filename, content_type=content_type)
        if isinstance(result, BlobError):
            return ImageError(error=result.error)
        return result

    # -- Manipulation --

    def resize(self, key: str, width: int | None = None, height: int | None = None) -> BlobRef | ImageError:
        """Resize an image. If only one dimension given, preserves aspect ratio."""
        from cogos.capabilities.image.manipulate import resize
        return resize(self, key, width, height)

    def crop(self, key: str, left: int, top: int, right: int, bottom: int) -> BlobRef | ImageError:
        """Crop an image to the given bounding box."""
        from cogos.capabilities.image.manipulate import crop
        return crop(self, key, left, top, right, bottom)

    def rotate(self, key: str, degrees: float) -> BlobRef | ImageError:
        """Rotate an image by the given degrees."""
        from cogos.capabilities.image.manipulate import rotate
        return rotate(self, key, degrees)

    def convert(self, key: str, format: str) -> BlobRef | ImageError:
        """Convert an image to a different format (PNG, JPEG, WEBP)."""
        from cogos.capabilities.image.manipulate import convert
        return convert(self, key, format)

    def thumbnail(self, key: str, max_size: int) -> BlobRef | ImageError:
        """Create a thumbnail that fits within a max_size x max_size box."""
        from cogos.capabilities.image.manipulate import thumbnail
        return thumbnail(self, key, max_size)

    # -- Compositing --

    def overlay_text(
        self, key: str, text: str, position: str = "center", font_size: int = 24, color: str = "white",
    ) -> BlobRef | ImageError:
        """Overlay text on an image."""
        from cogos.capabilities.image.compose import overlay_text
        return overlay_text(self, key, text, position, font_size, color)

    def watermark(
        self, key: str, watermark_key: str, position: str = "bottom-right", opacity: float = 0.5,
    ) -> BlobRef | ImageError:
        """Overlay a watermark image."""
        from cogos.capabilities.image.compose import watermark
        return watermark(self, key, watermark_key, position, opacity)

    def combine(self, keys: list[str], layout: str = "horizontal") -> BlobRef | ImageError:
        """Combine multiple images. Layout: horizontal, vertical, grid."""
        from cogos.capabilities.image.compose import combine
        return combine(self, keys, layout)

    # -- Analysis (Gemini Vision) --

    def describe(self, key: str, prompt: str | None = None) -> ImageDescription | ImageError:
        """Describe an image using Gemini Vision."""
        from cogos.capabilities.image.analyze import describe
        return describe(self, key, prompt)

    def analyze(self, key: str, prompt: str) -> AnalysisResult | ImageError:
        """Answer a question about an image."""
        from cogos.capabilities.image.analyze import analyze
        return analyze(self, key, prompt)

    def extract_text(self, key: str) -> ExtractedText | ImageError:
        """Extract text from an image (OCR via Gemini Vision)."""
        from cogos.capabilities.image.analyze import extract_text
        return extract_text(self, key)

    # -- Generation (Gemini) --

    def generate(self, prompt: str, size: str | None = None, style: str | None = None) -> BlobRef | ImageError:
        """Generate an image from a text prompt."""
        from cogos.capabilities.image.generate import generate
        return generate(self, prompt, size, style)

    def edit(self, key: str, prompt: str) -> BlobRef | ImageError:
        """Edit an existing image using a text prompt."""
        from cogos.capabilities.image.generate import edit
        return edit(self, key, prompt)

    def variations(self, key: str, count: int = 2) -> list[BlobRef] | ImageError:
        """Generate variations of an existing image."""
        from cogos.capabilities.image.generate import variations
        return variations(self, key, count)

    def __repr__(self) -> str:
        return (
            "<ImageCapability resize() crop() rotate() convert() thumbnail() overlay_text()"
            " watermark() combine() describe() analyze() extract_text() generate() edit() variations()>"
        )
