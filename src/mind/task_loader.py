"""Load task definitions from a directory of Markdown, YAML, and Python files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain.db.models import Task, TaskStatus
from brain.db.repository import Repository
from mind.loader import (
    SyncIssue,
    extract_pydantic_config,
    load_yaml,
    normalise_list_field,
    parse_frontmatter_optional,
    scan_dir,
    validate_memory_keys,
    validate_program_exists,
    validate_tools,
)


class CogentMindTask(BaseModel):
    """Pydantic config embedded in .py task files."""

    name: str = ""
    program_name: str = "vsm/s1/do-content"
    description: str = ""
    content: str = ""
    memory_keys: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    priority: float = 0.0
    runner: str | None = None
    clear_context: bool = False
    resources: list[str] = Field(default_factory=list)
    disabled: bool = False
    limits: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


def _load_markdown(path: Path, rel: str) -> Task:
    """Load a single markdown file as a task."""
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter_optional(text)

    name = rel.removesuffix(".md")
    fm.setdefault("name", name)
    fm.setdefault("program_name", "vsm/s1/do-content")
    fm["content"] = body.strip()

    return _task_from_dict(fm)


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


def _load_python(path: Path) -> Task:
    """Load a task from a .py file with CogentMindTask config."""
    source = path.read_text()
    try:
        kwargs = extract_pydantic_config(source, "CogentMindTask")
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"{path}: {exc}") from exc

    cfg = CogentMindTask(**kwargs)
    name = cfg.name or path.stem

    status = TaskStatus.DISABLED if cfg.disabled else TaskStatus.RUNNABLE
    return Task(
        name=name,
        program_name=cfg.program_name,
        description=cfg.description,
        content=cfg.content or source,
        memory_keys=cfg.memory_keys,
        tools=cfg.tools,
        priority=cfg.priority,
        runner=cfg.runner,
        clear_context=cfg.clear_context,
        resources=cfg.resources,
        status=status,
        limits=cfg.limits,
        metadata=cfg.metadata,
    )


# ─── Public API ─────────────────────────────────────────────


def load_tasks_from_dir(tasks_dir: Path) -> list[Task]:
    """Recursively load task definitions from a directory."""
    tasks: list[Task] = []
    for path in scan_dir(tasks_dir):
        rel = str(path.relative_to(tasks_dir))
        suffix = path.suffix.lower()

        if suffix == ".md":
            tasks.append(_load_markdown(path, rel))
        elif suffix in (".yaml", ".yml"):
            tasks.extend(_load_yaml(path))
        elif suffix == ".py":
            tasks.append(_load_python(path))

    return tasks


def validate_task(task: Task, repo: Repository) -> list[SyncIssue]:
    """Validate a task's program, tools, and memory keys against the DB."""
    issues: list[SyncIssue] = []
    issues.extend(validate_program_exists(task.name, task.program_name, repo))
    issues.extend(validate_tools(task.name, task.tools))
    issues.extend(validate_memory_keys(task.name, task.memory_keys, repo))
    return issues
