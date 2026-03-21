"""Image compositing functions — overlay_text, watermark, combine."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from cogos.capabilities.blob import BlobRef
from cogos.capabilities.image import ImageError

if TYPE_CHECKING:
    from cogos.capabilities.image import ImageCapability


# ── Position helpers ────────────────────────────────────────

_PAD = 10


def _position_xy(position: str, canvas_w: int, canvas_h: int, obj_w: int, obj_h: int) -> tuple[int, int]:
    """Return (x, y) for a named position with padding."""
    positions: dict[str, tuple[int, int]] = {
        "center": ((canvas_w - obj_w) // 2, (canvas_h - obj_h) // 2),
        "top": ((canvas_w - obj_w) // 2, _PAD),
        "bottom": ((canvas_w - obj_w) // 2, canvas_h - obj_h - _PAD),
        "top-left": (_PAD, _PAD),
        "top-right": (canvas_w - obj_w - _PAD, _PAD),
        "bottom-left": (_PAD, canvas_h - obj_h - _PAD),
        "bottom-right": (canvas_w - obj_w - _PAD, canvas_h - obj_h - _PAD),
    }
    return positions.get(position, positions["center"])


def _load_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try DejaVuSans, fall back to default."""
    try:
        return ImageFont.truetype("DejaVuSans.ttf", font_size)
    except (OSError, IOError):
        return ImageFont.load_default(size=font_size)


# ── Public compositing functions ────────────────────────────


def overlay_text(
    cap: ImageCapability,
    key: str,
    text: str,
    position: str = "center",
    font_size: int = 24,
    color: str = "white",
) -> BlobRef | ImageError:
    """Draw text on an image."""
    err = cap._check_op("overlay_text")
    if err:
        return ImageError(error=err)

    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)

    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x, y = _position_xy(position, img.width, img.height, text_w, text_h)
    draw.text((x, y), text, fill=color, font=font)

    return cap._upload_image(img, "text_overlay.png", "PNG")


def watermark(
    cap: ImageCapability,
    key: str,
    watermark_key: str,
    position: str = "bottom-right",
    opacity: float = 0.5,
) -> BlobRef | ImageError:
    """Overlay a watermark image."""
    err = cap._check_op("watermark")
    if err:
        return ImageError(error=err)

    base, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)

    wm, dl_err2 = cap._download_image(watermark_key)
    if dl_err2:
        return ImageError(error=dl_err2)

    base = base.convert("RGBA")
    wm = wm.convert("RGBA")

    # Apply opacity to watermark alpha channel
    r, g, b, alpha = wm.split()
    alpha = alpha.point(lambda p: int(p * opacity))
    wm = Image.merge("RGBA", (r, g, b, alpha))

    x, y = _position_xy(position, base.width, base.height, wm.width, wm.height)
    base.paste(wm, (x, y), mask=wm)

    return cap._upload_image(base, "watermarked.png", "PNG")


def combine(
    cap: ImageCapability,
    keys: list[str],
    layout: str = "horizontal",
) -> BlobRef | ImageError:
    """Combine multiple images. Layout: horizontal, vertical, grid."""
    err = cap._check_op("combine")
    if err:
        return ImageError(error=err)

    images = []
    for k in keys:
        img, dl_err = cap._download_image(k)
        if dl_err:
            return ImageError(error=dl_err)
        images.append(img.convert("RGBA"))

    if not images:
        return ImageError(error="No images to combine")

    if layout == "horizontal":
        total_w = sum(im.width for im in images)
        max_h = max(im.height for im in images)
        canvas = Image.new("RGBA", (total_w, max_h), (0, 0, 0, 0))
        x_off = 0
        for im in images:
            canvas.paste(im, (x_off, 0))
            x_off += im.width

    elif layout == "vertical":
        max_w = max(im.width for im in images)
        total_h = sum(im.height for im in images)
        canvas = Image.new("RGBA", (max_w, total_h), (0, 0, 0, 0))
        y_off = 0
        for im in images:
            canvas.paste(im, (0, y_off))
            y_off += im.height

    elif layout == "grid":
        cols = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / cols)
        cell_w = max(im.width for im in images)
        cell_h = max(im.height for im in images)
        canvas = Image.new("RGBA", (cols * cell_w, rows * cell_h), (0, 0, 0, 0))
        for idx, im in enumerate(images):
            r, c = divmod(idx, cols)
            canvas.paste(im, (c * cell_w, r * cell_h))

    else:
        return ImageError(error=f"Unknown layout: {layout}")

    return cap._upload_image(canvas, "combined.png", "PNG")
