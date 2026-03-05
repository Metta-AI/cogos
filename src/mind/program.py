"""Load program definitions from .py and .md files on disk, validate, and sync."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from brain.db.models import Program, ProgramType, Trigger, TriggerConfig
from brain.db.repository import Repository


class TriggerSpec(BaseModel):
    """Trigger declaration inside a program file."""

    pattern: str
    priority: int = 10
    config: dict[str, Any] = Field(default_factory=dict)


class CogentMindProgram(BaseModel):
    """Pydantic config embedded in .py program files."""

    name: str = ""
    program_type: str = "python"
    includes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    memory_keys: list[str] = Field(default_factory=list)
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Valid tool names: mind CLI subcommands and memory CLI commands.
VALID_TOOLS: set[str] = {
    # mind program
    "program list", "program info", "program add", "program delete",
    "program disable", "program runs", "program update",
    # mind task
    "task create", "task list", "task show", "task update",
    # mind trigger
    "trigger create", "trigger list", "trigger enable", "trigger disable", "trigger delete",
    # mind cron
    "cron create", "cron list", "cron enable", "cron disable", "cron delete",
    # mind event
    "event list", "event send", "event show", "event trace",
    # memory (separate CLI group, but available as tools)
    "memory create", "memory list", "memory get", "memory delete", "memory put",
}


@dataclass
class ProgramBundle:
    """A parsed program plus its declared triggers."""

    program: Program
    triggers: list[TriggerSpec] = field(default_factory=list)


@dataclass
class SyncIssue:
    """A warning or error found during validation."""

    program: str
    level: str  # "warn" or "error"
    message: str


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def _parse_md(path: Path) -> ProgramBundle:
    """Parse a .md file: YAML frontmatter -> metadata, body -> content."""
    text = path.read_text()
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: missing YAML frontmatter (--- ... ---)")
    fm = yaml.safe_load(match.group(1)) or {}
    content = text[match.end():]
    name = fm.pop("name", path.stem)
    program_type = fm.pop("program_type", "prompt")
    includes = fm.pop("includes", [])
    tools = fm.pop("tools", [])
    memory_keys = fm.pop("memory_keys", [])
    triggers_raw = fm.pop("triggers", [])
    metadata = fm.pop("metadata", {})
    # Any remaining frontmatter keys go into metadata
    metadata.update(fm)
    prog = Program(
        name=name,
        program_type=ProgramType(program_type),
        content=content.strip(),
        includes=includes or [],
        tools=tools or [],
        memory_keys=memory_keys or [],
        metadata=metadata,
    )
    triggers = [TriggerSpec(**t) for t in (triggers_raw or [])]
    return ProgramBundle(program=prog, triggers=triggers)


def _extract_config(source: str) -> dict[str, Any]:
    """Extract CogentMindProgram(...) kwargs from Python source via AST."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Call) and _is_config_call(node.value)):
            continue
        return _eval_call_kwargs(node.value)
    raise ValueError("No CogentMindProgram(...) assignment found")


def _is_config_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == "CogentMindProgram"
    if isinstance(call.func, ast.Attribute):
        return call.func.attr == "CogentMindProgram"
    return False


def _eval_call_kwargs(call: ast.Call) -> dict[str, Any]:
    """Safely evaluate keyword arguments of a CogentMindProgram() call."""
    result: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            continue
        result[kw.arg] = ast.literal_eval(kw.value)
    return result


def _parse_py(path: Path) -> ProgramBundle:
    """Parse a .py file: CogentMindProgram config -> metadata, full source -> content."""
    source = path.read_text()
    try:
        kwargs = _extract_config(source)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"{path}: {exc}") from exc

    cfg = CogentMindProgram(**kwargs)
    name = cfg.name or path.stem
    prog = Program(
        name=name,
        program_type=ProgramType(cfg.program_type),
        content=source,
        includes=cfg.includes,
        tools=cfg.tools,
        memory_keys=cfg.memory_keys,
        metadata=cfg.metadata,
    )
    triggers = [TriggerSpec(**t) for t in cfg.triggers]
    return ProgramBundle(program=prog, triggers=triggers)


def load_program(path: Path) -> ProgramBundle:
    """Load a single program from a .py or .md file."""
    if path.suffix == ".md":
        return _parse_md(path)
    if path.suffix == ".py":
        return _parse_py(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def load_programs_dir(root: Path) -> list[ProgramBundle]:
    """Recursively load all .py and .md programs under a directory."""
    bundles: list[ProgramBundle] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in (".py", ".md"):
            continue
        if path.name.startswith("_"):
            continue
        bundles.append(load_program(path))
    return bundles


def validate_tools(bundle: ProgramBundle) -> list[SyncIssue]:
    """Check that every tool in the program is a valid CLI command."""
    issues: list[SyncIssue] = []
    for tool in bundle.program.tools:
        if tool not in VALID_TOOLS:
            issues.append(SyncIssue(
                program=bundle.program.name,
                level="error",
                message=f"unknown tool '{tool}' (valid: {', '.join(sorted(VALID_TOOLS))})",
            ))
    return issues


def validate_memory(bundle: ProgramBundle, repo: Repository) -> list[SyncIssue]:
    """Check that every memory include key exists in the database."""
    issues: list[SyncIssue] = []
    includes = bundle.program.includes
    if not includes:
        return issues
    found = repo.query_memory_by_prefixes(includes)
    found_prefixes = {m.name for m in found if m.name}
    for key in includes:
        if not any(name.startswith(key) for name in found_prefixes):
            issues.append(SyncIssue(
                program=bundle.program.name,
                level="warn",
                message=f"memory include '{key}' not found (will be empty at runtime)",
            ))
    return issues


def sync_triggers(bundle: ProgramBundle, repo: Repository) -> list[str]:
    """Upsert triggers declared in the program. Returns list of synced pattern strings."""
    prog_name = bundle.program.name
    existing = repo.list_triggers(enabled_only=False, program_name=prog_name)
    existing_by_pattern = {t.event_pattern: t for t in existing}

    synced: list[str] = []
    declared_patterns: set[str] = set()

    for spec in bundle.triggers:
        declared_patterns.add(spec.pattern)
        if spec.pattern in existing_by_pattern:
            # Already exists — leave it (keeps its id/enabled state)
            synced.append(spec.pattern)
            continue
        trigger = Trigger(
            program_name=prog_name,
            event_pattern=spec.pattern,
            priority=spec.priority,
            config=TriggerConfig(**spec.config) if spec.config else TriggerConfig(),
        )
        repo.insert_trigger(trigger)
        synced.append(spec.pattern)

    # Remove triggers no longer declared
    for pattern, existing_trigger in existing_by_pattern.items():
        if pattern not in declared_patterns:
            repo.delete_trigger(existing_trigger.id)

    return synced


def sync_program(bundle: ProgramBundle, repo: Repository) -> tuple[str, list[SyncIssue]]:
    """Validate and sync a single program + triggers. Returns (program_id, issues)."""
    issues: list[SyncIssue] = []
    issues.extend(validate_tools(bundle))

    # Fail on errors
    errors = [i for i in issues if i.level == "error"]
    if errors:
        return "", issues

    # Upsert program first (triggers FK requires program to exist)
    prog_id = repo.upsert_program(bundle.program)

    # Validate memory (warn only)
    issues.extend(validate_memory(bundle, repo))

    # Sync triggers
    sync_triggers(bundle, repo)

    return str(prog_id), issues
