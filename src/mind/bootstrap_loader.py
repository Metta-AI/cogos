"""Load bootstrap.py: cron schedules, triggers, and bootstrap memory via AST extraction."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain.db.models import Cron, MemoryRecord, MemoryScope, Trigger, TriggerConfig
from brain.db.repository import Repository


# --- Pydantic config models (used in bootstrap.py files) ---


class CogentCron(BaseModel):
    cron_expression: str
    event_pattern: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CogentTrigger(BaseModel):
    program_name: str
    event_pattern: str
    priority: int = 10
    config: dict[str, Any] = Field(default_factory=dict)


class CogentMemory(BaseModel):
    name: str
    content: str = ""


# --- AST extraction ---


def _extract_list(source: str, var_name: str, cls_name: str) -> list[dict[str, Any]]:
    """Extract a list of Pydantic model kwargs from `var_name = [cls_name(...), ...]`."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t for t in node.targets if isinstance(t, ast.Name) and t.id == var_name]
        if not targets or not isinstance(node.value, ast.List):
            continue
        results: list[dict[str, Any]] = []
        for elt in node.value.elts:
            if not isinstance(elt, ast.Call):
                continue
            func = elt.func
            if not (
                (isinstance(func, ast.Name) and func.id == cls_name)
                or (isinstance(func, ast.Attribute) and func.attr == cls_name)
            ):
                continue
            kwargs: dict[str, Any] = {}
            for kw in elt.keywords:
                if kw.arg is None:
                    continue
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            results.append(kwargs)
        return results
    return []


# --- Sync ---


def sync_bootstrap(path: Path, repo: Repository) -> dict[str, int]:
    """Load and upsert cron, triggers, and memory from a bootstrap.py file.

    Returns counts of synced items by category.
    """
    source = path.read_text(encoding="utf-8")
    counts = {"cron": 0, "triggers": 0, "memory": 0}

    # Cron schedules
    for kwargs in _extract_list(source, "cron", "CogentCron"):
        cfg = CogentCron(**kwargs)
        existing = repo.list_cron(enabled_only=False)
        already = any(
            c.cron_expression == cfg.cron_expression and c.event_pattern == cfg.event_pattern
            for c in existing
        )
        if not already:
            repo.insert_cron(Cron(
                cron_expression=cfg.cron_expression,
                event_pattern=cfg.event_pattern,
                metadata=cfg.metadata,
            ))
        counts["cron"] += 1

    # Triggers
    for kwargs in _extract_list(source, "triggers", "CogentTrigger"):
        cfg = CogentTrigger(**kwargs)
        existing = repo.list_triggers(enabled_only=False, program_name=cfg.program_name)
        already = any(t.event_pattern == cfg.event_pattern for t in existing)
        if not already:
            repo.insert_trigger(Trigger(
                program_name=cfg.program_name,
                event_pattern=cfg.event_pattern,
                priority=cfg.priority,
                config=TriggerConfig(**cfg.config) if cfg.config else TriggerConfig(),
            ))
        counts["triggers"] += 1

    # Bootstrap memory
    for kwargs in _extract_list(source, "memory", "CogentMemory"):
        cfg = CogentMemory(**kwargs)
        existing = repo.get_memories_by_names([cfg.name])
        if not existing:
            repo.insert_memory(MemoryRecord(
                scope=MemoryScope.COGENT,
                name=cfg.name,
                content=cfg.content,
            ))
        counts["memory"] += 1

    return counts
