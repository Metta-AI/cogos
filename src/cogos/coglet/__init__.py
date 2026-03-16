"""Coglet: code+tests container with PR-style patch workflow."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from cogos.files.store import FileStore


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid4())


class PatchInfo(BaseModel):
    base_version: int
    test_passed: bool
    test_output: str = ""
    created_at: str = Field(default_factory=_now_iso)


class LogEntry(BaseModel):
    action: str  # "proposed", "merged", "discarded", "tests_run"
    patch_id: str | None = None
    version: int | None = None
    test_passed: bool | None = None
    test_output: str = ""
    timestamp: str = Field(default_factory=_now_iso)


class CogletMeta(BaseModel):
    id: str = Field(default_factory=_new_uuid)
    name: str
    test_command: str
    executor: str = "subprocess"
    timeout_seconds: int = 60
    version: int = 0
    created_at: str = Field(default_factory=_now_iso)
    patches: dict[str, PatchInfo] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    passed: bool
    exit_code: int
    output: str


def run_tests(
    test_command: str,
    file_tree: dict[str, str],
    timeout_seconds: int = 60,
) -> TestResult:
    """Materialize *file_tree* to a temp dir and run *test_command*."""
    with tempfile.TemporaryDirectory() as tmp:
        for rel_path, content in file_tree.items():
            full = os.path.join(tmp, rel_path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(content)

        try:
            proc = subprocess.run(
                test_command,
                shell=True,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            output = (proc.stdout + proc.stderr).strip()
            return TestResult(
                passed=proc.returncode == 0,
                exit_code=proc.returncode,
                output=output,
            )
        except subprocess.TimeoutExpired as exc:
            output = ""
            if exc.stdout:
                output += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode()
            if exc.stderr:
                output += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode()
            return TestResult(
                passed=False,
                exit_code=-1,
                output=output.strip() or "timeout",
            )


# ---------------------------------------------------------------------------
# File tree helpers
# ---------------------------------------------------------------------------


def _prefix(coglet_id: str, branch: str) -> str:
    return f"coglets/{coglet_id}/{branch}/"


def write_file_tree(
    store: FileStore,
    coglet_id: str,
    branch: str,
    files: dict[str, str],
) -> None:
    """Write *files* into the store under the coglet/branch prefix."""
    pfx = _prefix(coglet_id, branch)
    for rel_path, content in files.items():
        store.upsert(pfx + rel_path, content)


def read_file_tree(
    store: FileStore,
    coglet_id: str,
    branch: str,
) -> dict[str, str]:
    """Read all files under the coglet/branch prefix. Returns empty dict if none."""
    pfx = _prefix(coglet_id, branch)
    result: dict[str, str] = {}
    for f in store.list_files(prefix=pfx):
        content = store.get_content(f.key)
        if content is not None:
            result[f.key[len(pfx):]] = content
    return result


def delete_file_tree(
    store: FileStore,
    coglet_id: str,
    branch: str,
) -> int:
    """Delete all files under the coglet/branch prefix. Returns count deleted."""
    pfx = _prefix(coglet_id, branch)
    files = store.list_files(prefix=pfx)
    for f in files:
        store.delete(f.key)
    return len(files)


# ---------------------------------------------------------------------------
# Diff application
# ---------------------------------------------------------------------------


def apply_diff(files: dict[str, str], diff: str) -> dict[str, str]:
    """Apply a unified diff to a file tree dict. Returns a new dict."""
    result = dict(files)
    chunks = _parse_diff(diff)
    for file_diff in chunks:
        _apply_file_diff(result, file_diff)
    return result


def _parse_diff(diff: str) -> list[dict]:
    """Parse a unified diff string into per-file chunks."""
    lines = diff.split("\n")
    file_diffs: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise ValueError(f"Expected +++ line after --- at line {i + 1}")
            old_path = _extract_path(line[4:])
            new_path = _extract_path(lines[i + 1][4:])
            i += 2
            hunks: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("@@ "):
                hunk_lines: list[str] = [lines[i]]
                i += 1
                while i < len(lines) and not lines[i].startswith(("--- ", "@@ ")):
                    hunk_lines.append(lines[i])
                    i += 1
                hunks.append(hunk_lines)
            file_diffs.append({
                "old_path": old_path,
                "new_path": new_path,
                "hunks": hunks,
            })
        else:
            i += 1
    if not file_diffs:
        raise ValueError("No valid diff hunks found")
    return file_diffs


def _extract_path(raw: str) -> str | None:
    """Extract file path from a --- or +++ line, stripping a/ b/ prefixes."""
    path = raw.strip()
    if path == "/dev/null":
        return None
    # Strip a/ or b/ prefix
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _apply_file_diff(files: dict[str, str], file_diff: dict) -> None:
    old_path = file_diff["old_path"]
    new_path = file_diff["new_path"]
    hunks = file_diff["hunks"]

    # Deletion
    if new_path is None:
        if old_path and old_path in files:
            del files[old_path]
        return

    # Addition (new file)
    if old_path is None:
        content_lines: list[str] = []
        for hunk in hunks:
            for line in hunk[1:]:  # skip @@ header
                if line.startswith("+"):
                    content_lines.append(line[1:])
                elif line.startswith(" "):
                    content_lines.append(line[1:])
        files[new_path] = "\n".join(content_lines)
        return

    # Modification
    if old_path not in files:
        raise ValueError(f"Cannot modify '{old_path}': file not in tree")

    original_lines = files[old_path].split("\n")
    for hunk in hunks:
        header = hunk[0]
        old_start = _parse_hunk_header(header)
        offset = old_start - 1  # 0-indexed
        # Collect removals and additions
        remove_count = 0
        add_lines: list[str] = []
        context_before = 0
        started = False
        for line in hunk[1:]:
            if line.startswith("-"):
                started = True
                remove_count += 1
            elif line.startswith("+"):
                started = True
                add_lines.append(line[1:])
            elif line.startswith(" "):
                if not started:
                    context_before += 1
                else:
                    # trailing context — stop processing this hunk's changes
                    add_lines.append(line[1:])
                    remove_count += 1  # account for context line in old
            else:
                # empty line (no prefix) — treat as context
                if not started:
                    context_before += 1
                else:
                    add_lines.append(line)
                    remove_count += 1
        pos = offset + context_before
        # Remove old lines and insert new
        original_lines[pos:pos + remove_count] = add_lines

    # If old_path != new_path this is a rename
    if old_path != new_path:
        del files[old_path]
    files[new_path] = "\n".join(original_lines)


def _parse_hunk_header(header: str) -> int:
    """Extract old-file start line from @@ -N,M +N,M @@."""
    try:
        part = header.split("@@")[1].strip()
        old_range = part.split(" ")[0]  # -N,M
        start = old_range.split(",")[0]  # -N
        return int(start[1:])  # drop the '-'
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Malformed hunk header: {header}") from exc
