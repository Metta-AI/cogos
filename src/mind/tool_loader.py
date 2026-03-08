"""Load tool definitions from .py files on disk, validate, and sync to DB."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from brain.db.models import Tool
from mind.loader import scan_dir


def load_tool(path: Path, rel: str | None = None) -> Tool:
    """Import a .py file and read its ``tool`` attribute.

    *rel* is the path relative to the tools root (e.g. ``mind/memory/get.py``).
    The tool name is derived by stripping the ``.py`` suffix from *rel*, or
    falling back to ``path.stem`` when *rel* is not provided.
    """
    name = rel.removesuffix(".py") if rel else path.stem

    # Dynamic import of the tool module
    module_name = f"_tool_loader_.{name.replace('/', '.')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    tool: Tool = getattr(module, "tool", None)  # type: ignore[assignment]
    if tool is None:
        raise ValueError(f"{path}: missing 'tool' attribute")
    if not isinstance(tool, Tool):
        raise TypeError(f"{path}: 'tool' is {type(tool).__name__}, expected Tool")

    tool.name = name
    return tool


def load_tools_dir(root: Path) -> list[Tool]:
    """Recursively load all tool ``.py`` files under *root*.

    Uses :func:`mind.loader.scan_dir` to walk the directory (skips
    ``_``-prefixed files like ``__init__.py``).
    """
    tools: list[Tool] = []
    for p in scan_dir(root, {".py"}):
        rel = str(p.relative_to(root))
        tools.append(load_tool(p, rel=rel))
    return tools


def sync_tools(root: Path, repo) -> tuple[int, int]:
    """Load all tools from *root* and upsert them into the database.

    Returns ``(synced_count, error_count)``.
    """
    tools = load_tools_dir(root)
    synced = 0
    errors = 0
    for tool in tools:
        try:
            repo.upsert_tool(tool)
            synced += 1
        except Exception:
            errors += 1
    return synced, errors
