"""Load program definitions from .py and .md files on disk, validate, and sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain.db.models import Program, Trigger, TriggerConfig
from brain.db.repository import Repository
from memory.store import MemoryStore
from mind.loader import (
    SyncIssue,
    extract_pydantic_config,
    is_program_file,
    parse_frontmatter,
    scan_dir,
    validate_memory_keys,
    validate_tools,
)


class TriggerSpec(BaseModel):
    """Trigger declaration inside a program file."""

    pattern: str
    priority: int = 10
    config: dict[str, Any] = Field(default_factory=dict)


class CogentMindProgram(BaseModel):
    """Pydantic config embedded in .py program files."""

    name: str = ""
    includes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    memory_keys: list[str] = Field(default_factory=list)  # legacy alias for includes
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ProgramBundle:
    """A parsed program plus its declared triggers, content, and includes."""

    program: Program
    content: str = ""
    includes: list[str] = field(default_factory=list)
    triggers: list[TriggerSpec] = field(default_factory=list)


# ─── File parsers ───────────────────────────────────────────


def _parse_md(path: Path, rel: str | None = None) -> ProgramBundle:
    """Parse a .md file: YAML frontmatter -> metadata, body -> content."""
    text = path.read_text()
    try:
        fm, body = parse_frontmatter(text)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc

    default_name = rel.removesuffix(".md") if rel else path.stem
    name = fm.pop("name", default_name)
    fm.pop("program_type", None)  # no longer stored; inferred from content
    includes = fm.pop("includes", [])  # includes for the memory
    tools = fm.pop("tools", [])
    memory_keys = fm.pop("memory_keys", [])  # legacy alias for includes
    triggers_raw = fm.pop("triggers", [])
    metadata = fm.pop("metadata", {})
    # Any remaining frontmatter keys go into metadata
    metadata.update(fm)
    # Merge includes and memory_keys (memory_keys is a legacy alias)
    all_includes = list(dict.fromkeys((includes or []) + (memory_keys or [])))
    prog = Program(
        name=name,
        tools=tools or [],
        metadata=metadata,
    )
    triggers = [TriggerSpec(**t) for t in (triggers_raw or [])]
    return ProgramBundle(program=prog, content=body.strip(), includes=all_includes, triggers=triggers)


def _parse_py(path: Path, rel: str | None = None) -> ProgramBundle:
    """Parse a .py file: CogentMindProgram config -> metadata, full source -> content.

    If no CogentMindProgram assignment is found, infer name from filename
    and treat as a python program with the source as content.
    """
    default_name = rel.removesuffix(".py") if rel else path.stem
    source = path.read_text()
    try:
        kwargs = extract_pydantic_config(source, "CogentMindProgram")
    except (ValueError, SyntaxError):
        # No config block — infer from filename
        prog = Program(name=default_name)
        return ProgramBundle(program=prog, content=source, triggers=[])

    cfg = CogentMindProgram(**kwargs)
    name = cfg.name or default_name
    all_includes = list(dict.fromkeys(cfg.includes + cfg.memory_keys))
    prog = Program(
        name=name,
        tools=cfg.tools,
        metadata=cfg.metadata,
    )
    triggers = [TriggerSpec(**t) for t in cfg.triggers]
    return ProgramBundle(program=prog, content=source, includes=all_includes, triggers=triggers)


# ─── Public API ─────────────────────────────────────────────


def load_program(path: Path, rel: str | None = None) -> ProgramBundle:
    """Load a single program from a .py or .md file."""
    if path.suffix == ".md":
        return _parse_md(path, rel=rel)
    if path.suffix == ".py":
        return _parse_py(path, rel=rel)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def load_programs_dir(root: Path) -> list[ProgramBundle]:
    """Recursively load program files (.py and .md with program frontmatter).

    Program names are derived from relative paths (e.g. vsm/s1/do-content).
    Skips plain memory files that lack program configuration.
    """
    bundles = []
    for p in scan_dir(root, {".py", ".md"}):
        if not is_program_file(p):
            continue
        rel = str(p.relative_to(root))
        bundles.append(load_program(p, rel=rel))
    return bundles


def validate_bundle(bundle: ProgramBundle) -> list[SyncIssue]:
    """Validate tools (offline, no DB needed)."""
    return validate_tools(bundle.program.name, bundle.program.tools)


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
    issues = validate_bundle(bundle)

    # Fail on errors
    if any(i.level == "error" for i in issues):
        return "", issues

    # Store program content as a memory under programs/{name}
    memory_store = MemoryStore(repo)
    memory_name = f"programs/{bundle.program.name}"
    mem = memory_store.get(memory_name)
    if mem is None:
        mem = memory_store.create(
            memory_name, bundle.content,
            source="polis", read_only=True,
        )
    else:
        # new_version bypasses read_only check on current version
        memory_store.new_version(
            memory_name, bundle.content,
            source="polis", read_only=True,
        )

    # Set includes on the memory
    if bundle.includes != (mem.includes or []):
        memory_store.update_includes(memory_name, bundle.includes)

    bundle.program.memory_id = mem.id

    # Upsert program (triggers FK requires program to exist)
    prog_id = repo.upsert_program(bundle.program)

    # Validate includes (warn only)
    issues.extend(validate_memory_keys(
        bundle.program.name, bundle.includes, repo,
    ))

    # Sync triggers
    sync_triggers(bundle, repo)

    return str(prog_id), issues
