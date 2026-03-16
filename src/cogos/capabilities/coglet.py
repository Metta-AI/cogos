"""CogletCapability — operate on a single coglet (tendril)."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.coglets import CogletError, _load_meta, _save_meta
from cogos.coglet import (
    CogletMeta,
    LogEntry,
    PatchInfo,
    apply_diff,
    delete_file_tree,
    read_file_tree,
    run_tests,
    write_file_tree,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class PatchResult(BaseModel):
    patch_id: str
    base_version: int
    test_passed: bool
    test_output: str = ""


class MergeResult(BaseModel):
    merged: bool
    new_version: int | None = None
    conflict: bool = False
    current_version: int | None = None
    base_version: int | None = None


class DiscardResult(BaseModel):
    discarded: bool
    patch_id: str


class PatchSummary(BaseModel):
    patch_id: str
    base_version: int
    test_passed: bool
    test_output: str = ""
    created_at: str = ""


class CogletStatus(BaseModel):
    coglet_id: str
    name: str
    version: int
    patch_count: int


class TestResultInfo(BaseModel):
    passed: bool
    output: str


# ── Log helpers ──────────────────────────────────────────────


def _log_key(coglet_id: str) -> str:
    return f"coglets/{coglet_id}/log"


def _append_log(store: FileStore, coglet_id: str, entry: LogEntry) -> None:
    """Append a log entry as JSONL."""
    line = entry.model_dump_json() + "\n"
    store.append(_log_key(coglet_id), line)


def _read_log(store: FileStore, coglet_id: str) -> list[LogEntry]:
    """Read all log entries."""
    content = store.get_content(_log_key(coglet_id))
    if not content:
        return []
    entries: list[LogEntry] = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if line:
            entries.append(LogEntry.model_validate_json(line))
    return entries


# ── Capability ───────────────────────────────────────────────


class CogletCapability(Capability):
    """Operate on a single coglet: patches, files, tests.

    Must be scoped with a coglet_id before use.

    Usage:
        coglet.propose_patch(diff)
        coglet.merge_patch(patch_id)
        coglet.discard_patch(patch_id)
        coglet.read_file("src/main.py")
        coglet.list_files()
        coglet.list_patches()
        coglet.get_status()
        coglet.run_tests()
        coglet.get_log()
    """

    ALL_OPS = {
        "propose_patch",
        "merge_patch",
        "discard_patch",
        "read_file",
        "list_files",
        "list_patches",
        "get_status",
        "run_tests",
        "get_log",
    }

    def _coglet_id(self) -> str:
        """Get the coglet_id from scope, raising if not set."""
        cid = self._scope.get("coglet_id")
        if not cid:
            raise PermissionError("CogletCapability requires coglet_id in scope")
        return cid

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        # Ops intersection
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        # coglet_id: cannot change once set
        old_id = existing.get("coglet_id")
        new_id = requested.get("coglet_id")
        if old_id is not None and new_id is not None and old_id != new_id:
            raise ValueError(
                f"Cannot change coglet_id from '{old_id}' to '{new_id}'"
            )
        result["coglet_id"] = old_id or new_id
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(
                f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})"
            )

    def propose_patch(self, diff: str) -> PatchResult | CogletError:
        """Apply a unified diff to create a patch branch, then run tests."""
        self._check("propose_patch")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        # Read current main files
        main_files = read_file_tree(store, coglet_id, "main")

        # Apply diff
        try:
            patched_files = apply_diff(main_files, diff)
        except ValueError as e:
            return CogletError(error=f"Failed to apply diff: {e}")

        # Create patch branch
        patch_id = str(uuid4())
        write_file_tree(store, coglet_id, f"patches/{patch_id}", patched_files)

        # Run tests
        result = run_tests(
            meta.test_command, patched_files, timeout_seconds=meta.timeout_seconds
        )

        # Record patch in meta
        patch_info = PatchInfo(
            base_version=meta.version,
            test_passed=result.passed,
            test_output=result.output,
        )
        meta.patches[patch_id] = patch_info
        _save_meta(store, meta)

        # Log
        _append_log(
            store,
            coglet_id,
            LogEntry(
                action="proposed",
                patch_id=patch_id,
                version=meta.version,
                test_passed=result.passed,
                test_output=result.output,
            ),
        )

        return PatchResult(
            patch_id=patch_id,
            base_version=meta.version,
            test_passed=result.passed,
            test_output=result.output,
        )

    def merge_patch(self, patch_id: str) -> MergeResult | CogletError:
        """Merge a patch into main (optimistic concurrency)."""
        self._check("merge_patch")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        patch_info = meta.patches.get(patch_id)
        if patch_info is None:
            return CogletError(error=f"Patch '{patch_id}' not found")

        # Check tests passed
        if not patch_info.test_passed:
            return CogletError(error=f"Patch '{patch_id}' has failing tests")

        # Optimistic concurrency: base_version must match current version
        if patch_info.base_version != meta.version:
            return MergeResult(
                merged=False,
                conflict=True,
                current_version=meta.version,
                base_version=patch_info.base_version,
            )

        # Read patch files and promote to main
        patch_files = read_file_tree(store, coglet_id, f"patches/{patch_id}")
        if not patch_files:
            return CogletError(error=f"Patch '{patch_id}' has no files")

        # Delete old main files and write new ones
        delete_file_tree(store, coglet_id, "main")
        write_file_tree(store, coglet_id, "main", patch_files)

        # Bump version, remove patch from meta
        meta.version += 1
        del meta.patches[patch_id]
        _save_meta(store, meta)

        # Clean up patch branch
        delete_file_tree(store, coglet_id, f"patches/{patch_id}")

        # Log
        _append_log(
            store,
            coglet_id,
            LogEntry(
                action="merged",
                patch_id=patch_id,
                version=meta.version,
            ),
        )

        return MergeResult(merged=True, new_version=meta.version)

    def discard_patch(self, patch_id: str) -> DiscardResult | CogletError:
        """Discard a patch branch."""
        self._check("discard_patch")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        if patch_id not in meta.patches:
            return CogletError(error=f"Patch '{patch_id}' not found")

        # Delete patch files
        delete_file_tree(store, coglet_id, f"patches/{patch_id}")

        # Remove from meta
        del meta.patches[patch_id]
        _save_meta(store, meta)

        # Log
        _append_log(
            store,
            coglet_id,
            LogEntry(action="discarded", patch_id=patch_id),
        )

        return DiscardResult(discarded=True, patch_id=patch_id)

    def read_file(self, path: str, patch_id: str | None = None) -> str | CogletError:
        """Read a file from main or a patch branch."""
        self._check("read_file")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        branch = f"patches/{patch_id}" if patch_id else "main"
        files = read_file_tree(store, coglet_id, branch)
        if path not in files:
            return CogletError(error=f"File '{path}' not found in {branch}")
        return files[path]

    def list_files(self, patch_id: str | None = None) -> list[str]:
        """List files in main or a patch branch."""
        self._check("list_files")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        branch = f"patches/{patch_id}" if patch_id else "main"
        files = read_file_tree(store, coglet_id, branch)
        return sorted(files.keys())

    def list_patches(self) -> list[PatchSummary]:
        """List all patches for this coglet."""
        self._check("list_patches")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return []

        return [
            PatchSummary(
                patch_id=pid,
                base_version=p.base_version,
                test_passed=p.test_passed,
                test_output=p.test_output,
                created_at=p.created_at,
            )
            for pid, p in meta.patches.items()
        ]

    def get_status(self) -> CogletStatus | CogletError:
        """Get coglet status."""
        self._check("get_status")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        return CogletStatus(
            coglet_id=meta.id,
            name=meta.name,
            version=meta.version,
            patch_count=len(meta.patches),
        )

    def run_tests(self) -> TestResultInfo | CogletError:
        """Run tests on the main branch files."""
        self._check("run_tests")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        main_files = read_file_tree(store, coglet_id, "main")
        result = run_tests(
            meta.test_command, main_files, timeout_seconds=meta.timeout_seconds
        )

        # Log
        _append_log(
            store,
            coglet_id,
            LogEntry(
                action="tests_run",
                test_passed=result.passed,
                test_output=result.output,
            ),
        )

        return TestResultInfo(passed=result.passed, output=result.output)

    def get_log(self) -> list[LogEntry]:
        """Read the coglet's log (JSONL)."""
        self._check("get_log")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)
        return _read_log(store, coglet_id)

    def __repr__(self) -> str:
        return "<CogletCapability propose_patch() merge_patch() discard_patch() read_file() list_files() list_patches() get_status() run_tests() get_log()>"
