from __future__ import annotations

import mimetypes
from dataclasses import dataclass

HTML_PREFIXES = ("<!doctype html", "<html", "<head", "<body")


@dataclass(frozen=True)
class StaticWebFile:
    key: str
    content: str
    content_type: str
    is_base64: bool


def content_type_for_path(path: str, content: str | None = None) -> str:
    content_type, _ = mimetypes.guess_type(path)
    if content_type:
        return content_type
    if content and looks_like_html(content):
        return "text/html"
    return "application/octet-stream"


def looks_like_html(content: str) -> bool:
    stripped = content.lstrip().lower()
    return any(stripped.startswith(prefix) for prefix in HTML_PREFIXES)


def static_file_keys(path: str) -> list[str]:
    normalized = path.lstrip("/")
    if not normalized:
        return ["web/index.html"]
    if normalized.endswith("/"):
        return [f"web/{normalized}index.html"]
    return [f"web/{normalized}", f"web/{normalized}/index.html"]


def lookup_static_file(store, path: str) -> StaticWebFile | None:  # noqa: ANN001
    for key in static_file_keys(path):
        content = store.get_content(key)
        if content is None:
            continue
        is_base64 = content.startswith("base64:")
        body = content[7:] if is_base64 else content
        return StaticWebFile(
            key=key,
            content=body,
            content_type=content_type_for_path(key, body),
            is_base64=is_base64,
        )
    return None
