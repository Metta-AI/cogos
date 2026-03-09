"""Load memory definitions from a directory of Markdown and YAML files."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mind.loader import is_program_file, load_yaml, parse_frontmatter_optional, scan_dir


@dataclass
class LoadedMemory:
    """A memory definition loaded from disk (not yet persisted)."""
    name: str
    content: str
    source: str = "polis"
    includes: list[str] = field(default_factory=list)


def _mem_from_dict(d: dict[str, Any]) -> LoadedMemory:
    source = d.pop("source", d.pop("scope", "polis"))
    # Map old scope values
    if source in ("cogent", "polis"):
        pass  # already valid
    elif not source.startswith("user:"):
        source = "polis"
    includes = d.pop("includes", []) or []
    return LoadedMemory(
        name=d.get("name", ""),
        content=d.get("content", ""),
        source=source,
        includes=includes,
    )


def _load_markdown(path: Path, rel: str) -> LoadedMemory:
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter_optional(text)
    name = rel.removesuffix(".md")
    fm.setdefault("name", name)
    fm["content"] = body.strip()
    return _mem_from_dict(fm)


def _load_yaml(path: Path) -> list[LoadedMemory]:
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


def load_memories_from_dir(memories_dir: Path) -> list[LoadedMemory]:
    memories: list[LoadedMemory] = []
    for path in scan_dir(memories_dir, suffixes={".md", ".yaml", ".yml"}):
        if is_program_file(path):
            continue
        rel = str(path.relative_to(memories_dir))
        suffix = path.suffix.lower()
        if suffix == ".md":
            memories.append(_load_markdown(path, rel))
        elif suffix in (".yaml", ".yml"):
            memories.extend(_load_yaml(path))
    return memories
