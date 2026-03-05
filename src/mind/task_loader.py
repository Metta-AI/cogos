"""Load task definitions from a directory of Markdown, YAML, and Python files."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

from brain.db.models import Task, TaskStatus
from brain.db.repository import Repository
from mind.loader import (
    SyncIssue,
    load_yaml,
    normalise_list_field,
    parse_frontmatter_optional,
    scan_dir,
    validate_memory_keys,
    validate_program_exists,
    validate_tools,
)


def _task_from_dict(d: dict[str, Any]) -> Task:
    """Build a Task from a raw dict (YAML or frontmatter fields)."""
    if d.pop("disabled", False):
        d.setdefault("status", TaskStatus.DISABLED)
    else:
        d.setdefault("status", TaskStatus.RUNNABLE)

    if isinstance(d.get("status"), str):
        d["status"] = TaskStatus(d["status"])

    for key in ("memory_keys", "tools", "resources"):
        normalise_list_field(d, key)

    return Task(**d)


def _load_markdown(path: Path, rel: str) -> list[Task]:
    """Load a single markdown file as a task."""
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter_optional(text)

    name = rel.removesuffix(".md")
    fm.setdefault("name", name)
    fm.setdefault("program_name", "do-content")
    fm["content"] = body

    return [_task_from_dict(fm)]


def _load_yaml(path: Path) -> list[Task]:
    """Load tasks from a YAML file."""
    raw = load_yaml(path)
    if not raw:
        return []

    if isinstance(raw, list):
        return [_task_from_dict(d) for d in raw]

    if isinstance(raw, dict) and "tasks" in raw:
        return [_task_from_dict(d) for d in raw["tasks"]]

    if isinstance(raw, dict) and "name" in raw:
        return [_task_from_dict(raw)]

    return []


def _load_python(path: Path) -> list[Task]:
    """Load tasks from a Python file defining task or tasks at module level."""
    spec = importlib.util.spec_from_file_location("_task_module", path)
    if spec is None or spec.loader is None:
        return []

    module = importlib.util.module_from_spec(spec)
    sys.modules["_task_module"] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        sys.modules.pop("_task_module", None)

    tasks: list[Task] = []
    if hasattr(module, "tasks"):
        tasks.extend(module.tasks)
    elif hasattr(module, "task"):
        tasks.append(module.task)
    return tasks


# ─── Public API ─────────────────────────────────────────────


def load_tasks_from_dir(tasks_dir: Path) -> list[Task]:
    """Recursively load task definitions from a directory."""
    tasks: list[Task] = []
    for path in scan_dir(tasks_dir):
        rel = str(path.relative_to(tasks_dir))
        suffix = path.suffix.lower()

        if suffix == ".md":
            tasks.extend(_load_markdown(path, rel))
        elif suffix in (".yaml", ".yml"):
            tasks.extend(_load_yaml(path))
        elif suffix == ".py":
            tasks.extend(_load_python(path))

    return tasks


def validate_task(task: Task, repo: Repository) -> list[SyncIssue]:
    """Validate a task's program, tools, and memory keys against the DB."""
    issues: list[SyncIssue] = []
    issues.extend(validate_program_exists(task.name, task.program_name, repo))
    issues.extend(validate_tools(task.name, task.tools))
    issues.extend(validate_memory_keys(task.name, task.memory_keys, repo))
    return issues
