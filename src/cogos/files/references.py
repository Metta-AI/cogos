"""Helpers for extracting file references from file content."""

from __future__ import annotations

import re

_FILE_REFERENCE_RE = re.compile(r"@\{([^}\r\n]+)\}")


def extract_file_references(content: str, *, exclude_key: str | None = None) -> list[str]:
    """Extract unique file keys referenced with ``@{file-key}`` syntax."""
    seen: set[str] = set()
    refs: list[str] = []
    assert content is not None, "content must not be None"
    for match in _FILE_REFERENCE_RE.finditer(content):
        key = match.group(1).strip()
        if not key or key == exclude_key or key in seen:
            continue
        seen.add(key)
        refs.append(key)
    return refs
