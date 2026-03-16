"""Image generation operations — generate, edit, variations via Gemini."""
from __future__ import annotations

import logging

from cogos.capabilities.blob import BlobRef, BlobError
from cogos.capabilities.image import ImageError
from google.genai import types

from cogos.capabilities.image._gemini_helper import get_gemini_client

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash-image"


def _image_to_part(img_bytes: bytes, mime_type: str = "image/png"):
    """Convert raw image bytes into a Gemini inline_data Part."""
    return types.Part(inline_data=types.Blob(data=img_bytes, mime_type=mime_type))


def _extract_image_from_response(response) -> bytes | None:
    """Extract image bytes from a Gemini response, or None if not found."""
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    return None


def generate(cap, prompt: str, size: str | None = None, style: str | None = None) -> BlobRef | ImageError:
    """Generate an image from a text prompt using Gemini."""
    err = cap._check_op("generate")
    if err:
        return ImageError(error=err)

    full_prompt = prompt
    if style:
        full_prompt += f" Style: {style}."
    if size:
        full_prompt += f" Image size: {size}."

    client = get_gemini_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )

    img_bytes = _extract_image_from_response(response)
    if img_bytes is None:
        return ImageError(error="No image returned by model")

    result = cap._blob.upload(img_bytes, "generated.png", content_type="image/png")
    if isinstance(result, BlobError):
        return ImageError(error=result.error)
    return result


def edit(cap, key: str, prompt: str) -> BlobRef | ImageError:
    """Edit an existing image using a text prompt via Gemini."""
    err = cap._check_op("edit")
    if err:
        return ImageError(error=err)

    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    image_part = _image_to_part(img_bytes)

    client = get_gemini_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt, image_part],
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )

    result_bytes = _extract_image_from_response(response)
    if result_bytes is None:
        return ImageError(error="No image returned by model")

    result = cap._blob.upload(result_bytes, "edited.png", content_type="image/png")
    if isinstance(result, BlobError):
        return ImageError(error=result.error)
    return result


def variations(cap, key: str, count: int = 2) -> list[BlobRef] | ImageError:
    """Generate variations of an existing image via Gemini."""
    err = cap._check_op("variations")
    if err:
        return ImageError(error=err)

    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    image_part = _image_to_part(img_bytes)
    client = get_gemini_client()

    refs: list[BlobRef] = []
    for i in range(count):
        prompt = f"Generate a creative variation (#{i + 1}) of this image, keeping the same subject but with a different artistic interpretation."
        response = client.models.generate_content(
            model=MODEL,
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        )
        result_bytes = _extract_image_from_response(response)
        if result_bytes is None:
            return ImageError(error=f"No image returned for variation #{i + 1}")

        result = cap._blob.upload(result_bytes, f"variation_{i + 1}.png", content_type="image/png")
        if isinstance(result, BlobError):
            return ImageError(error=result.error)
        refs.append(result)

    return refs
