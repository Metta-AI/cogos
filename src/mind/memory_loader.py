"""Load memory definitions from a directory of Markdown and YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from brain.db.models import MemoryRecord, MemoryScope
from mind.loader import (
    load_yaml,
    parse_frontmatter_optional,
    scan_dir,
)


def _mem_from_dict(d: dict[str, Any]) -> MemoryRecord:
    """Build a MemoryRecord from a raw dict."""
    scope_str = d.pop("scope", "cogent")
    scope = MemoryScope(scope_str) if isinstance(scope_str, str) else scope_str

    return MemoryRecord(
        scope=scope,
        name=d.get("name", ""),
        content=d.get("content", ""),
        provenance=d.get("provenance", {}),
    )


def _load_markdown(path: Path, rel: str) -> MemoryRecord:
    """Load a single markdown file as a memory entry."""
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter_optional(text)

    name = rel.removesuffix(".md")
    fm.setdefault("name", name)
    fm["content"] = body.strip()

    return _mem_from_dict(fm)


def _load_yaml(path: Path) -> list[MemoryRecord]:
    """Load memory entries from a YAML file."""
    raw = load_yaml(path)
    if not raw:
        return []

    if isinstance(raw, list):
        return [_mem_from_dict(d) for d in raw]

    if isinstance(raw, dict) and "memories" in raw:
        return [_mem_from_dict(d) for d in raw["memories"]]

    if isinstance(raw, dict) and "name" in raw:
        return [_mem_from_dict(raw)]

    return []


def load_memories_from_dir(memories_dir: Path) -> list[MemoryRecord]:
    """Recursively load memory definitions from a directory."""
    memories: list[MemoryRecord] = []
    for path in scan_dir(memories_dir, suffixes={".md", ".yaml", ".yml"}):
        rel = str(path.relative_to(memories_dir))
        suffix = path.suffix.lower()

        if suffix == ".md":
            memories.append(_load_markdown(path, rel))
        elif suffix in (".yaml", ".yml"):
            memories.extend(_load_yaml(path))

    return memories
