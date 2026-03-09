"""Unified file loader for mind resources (programs, tasks).

Shared infrastructure for loading .md, .yaml, .yml, and .py files from
directories with frontmatter parsing, validation, and DB sync.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from brain.db.models import Resource, ResourceType
from brain.db.repository import Repository

# Valid tool names: mind CLI subcommands and memory CLI commands.
VALID_TOOLS: set[str] = {
    # mind program
    "program list", "program info", "program add", "program delete",
    "program disable", "program runs", "program update",
    # mind task
    "task create", "task list", "task show", "task update",
    "task disable", "task enable", "task load",
    # mind trigger
    "trigger create", "trigger list", "trigger enable", "trigger disable", "trigger delete",
    # mind cron
    "cron create", "cron list", "cron enable", "cron disable", "cron delete",
    # mind event
    "event list", "event send", "event show", "event trace",
    # mind resource
    "resource create", "resource list", "resource show", "resource delete",
    # memory (separate CLI group, but available as tools)
    "memory create", "memory list", "memory get", "memory delete", "memory put",
}


@dataclass
class SyncIssue:
    """A warning or error found during validation."""

    name: str
    level: str  # "warn" or "error"
    message: str


# ─── Frontmatter / YAML parsing ────────────────────────────

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from body text.

    Returns (frontmatter_dict, body). Raises ValueError if no frontmatter found.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("missing YAML frontmatter (--- ... ---)")
    fm = yaml.safe_load(match.group(1)) or {}
    body = text[match.end():]
    return fm, body


def parse_frontmatter_optional(text: str) -> tuple[dict[str, Any], str]:
    """Split optional YAML frontmatter from body. Returns ({}, text) if none."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm = yaml.safe_load(match.group(1)) or {}
    return fm if isinstance(fm, dict) else {}, text[match.end():]


def load_yaml(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a YAML file, returning dict or list of dicts."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    return raw


# ─── Python config extraction ──────────────────────────────


def extract_pydantic_config(source: str, class_name: str) -> dict[str, Any]:
    """Extract kwargs from a Pydantic model assignment like `config = ClassName(...)`.

    Uses AST for safe extraction without executing the file.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        name_match = (
            (isinstance(func, ast.Name) and func.id == class_name)
            or (isinstance(func, ast.Attribute) and func.attr == class_name)
        )
        if not name_match:
            continue
        result: dict[str, Any] = {}
        for kw in node.value.keywords:
            if kw.arg is None:
                continue
            result[kw.arg] = ast.literal_eval(kw.value)
        return result
    raise ValueError(f"No {class_name}(...) assignment found")


# ─── Directory scanning ────────────────────────────────────

SUPPORTED_SUFFIXES = {".md", ".yaml", ".yml", ".py"}


def scan_dir(root: Path, suffixes: set[str] | None = None) -> list[Path]:
    """Recursively find files with matching suffixes, sorted, skipping _-prefixed."""
    allowed = suffixes or SUPPORTED_SUFFIXES
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix in allowed and not p.name.startswith("_")
    )


_PROGRAM_FM_KEYS = {"tools", "triggers", "memory_keys", "runner"}


def is_program_file(path: Path) -> bool:
    """Check if a file is a program (vs a plain memory).

    .py files with CogentMindProgram or def run() are programs.
    .md files with program frontmatter keys (tools, triggers, etc.) are programs.
    """
    if path.suffix == ".py":
        try:
            source = path.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "run":
                    return True
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if (isinstance(func, ast.Name) and func.id == "CogentMindProgram") or \
                       (isinstance(func, ast.Attribute) and func.attr == "CogentMindProgram"):
                        return True
        except (SyntaxError, OSError):
            pass
        return False
    if path.suffix == ".md":
        try:
            text = path.read_text()
            fm, _ = parse_frontmatter_optional(text)
            return bool(fm.keys() & _PROGRAM_FM_KEYS)
        except OSError:
            pass
    return False


# ─── Normalisation helpers ──────────────────────────────────


def normalise_list_field(d: dict[str, Any], key: str) -> None:
    """Convert comma-separated string to list in-place, or ensure list."""
    val = d.get(key)
    if isinstance(val, str):
        d[key] = [s.strip() for s in val.split(",") if s.strip()]
    elif val is None:
        d[key] = []


# ─── Validation ─────────────────────────────────────────────


def validate_tools(name: str, tools: list[str]) -> list[SyncIssue]:
    """Check that every tool is a valid CLI command."""
    issues: list[SyncIssue] = []
    for tool in tools:
        if tool not in VALID_TOOLS:
            issues.append(SyncIssue(
                name=name,
                level="error",
                message=f"unknown tool '{tool}'",
            ))
    return issues


def validate_memory_keys(name: str, keys: list[str], repo: Repository) -> list[SyncIssue]:
    """Check that memory keys/prefixes exist in the database."""
    issues: list[SyncIssue] = []
    if not keys:
        return issues
    found = repo.resolve_memory_keys(keys)
    found_names = {m.name for m in found if m.name}
    for key in keys:
        if not any(n.startswith(key) for n in found_names):
            issues.append(SyncIssue(
                name=name,
                level="warn",
                message=f"memory key '{key}' not found (will be empty at runtime)",
            ))
    return issues


def validate_program_exists(name: str, program_name: str, repo: Repository) -> list[SyncIssue]:
    """Check that a referenced program exists."""
    prog = repo.get_program(program_name)
    if not prog:
        return [SyncIssue(
            name=name,
            level="error",
            message=f"program '{program_name}' not found",
        )]
    return []


# ─── Resources ──────────────────────────────────────────────


class CogentMindResource(BaseModel):
    """Pydantic config for resource definitions."""

    name: str
    resource_type: str = "pool"
    capacity: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_resources(path: Path) -> list[Resource]:
    """Load resources from a .py file containing a `resources` list of CogentMindResource."""
    source = path.read_text()
    tree = ast.parse(source)

    results: list[Resource] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # Look for `resources = [...]`
        targets = [t for t in node.targets if isinstance(t, ast.Name) and t.id == "resources"]
        if not targets or not isinstance(node.value, ast.List):
            continue
        for elt in node.value.elts:
            if not isinstance(elt, ast.Call):
                continue
            func = elt.func
            if not (
                (isinstance(func, ast.Name) and func.id == "CogentMindResource")
                or (isinstance(func, ast.Attribute) and func.attr == "CogentMindResource")
            ):
                continue
            kwargs: dict[str, Any] = {}
            for kw in elt.keywords:
                if kw.arg is None:
                    continue
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            cfg = CogentMindResource(**kwargs)
            results.append(Resource(
                name=cfg.name,
                resource_type=ResourceType(cfg.resource_type),
                capacity=cfg.capacity,
                metadata=cfg.metadata,
            ))
        return results

    raise ValueError(f"{path}: no `resources = [...]` list found")


def sync_resources(path: Path, repo: Repository) -> list[str]:
    """Load and upsert all resources from a file. Returns list of synced names."""
    resources = load_resources(path)
    synced: list[str] = []
    for r in resources:
        repo.upsert_resource(r)
        synced.append(r.name)
    return synced
