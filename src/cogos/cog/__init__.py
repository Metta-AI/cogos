"""Cog: a named group that creates and owns coglets."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from cogos.coglet import (
    CogletMeta,
    LogEntry,
    PatchInfo,
    TestResult,
    apply_diff,
    run_tests,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Storage helpers — cog-namespaced paths
# ---------------------------------------------------------------------------

def _cog_meta_key(cog_name: str) -> str:
    return f"cogs/{cog_name}/meta.json"


def _coglet_prefix(cog_name: str, coglet_name: str, branch: str) -> str:
    return f"cogs/{cog_name}/coglets/{coglet_name}/{branch}/"


def _coglet_meta_key(cog_name: str, coglet_name: str) -> str:
    return f"cogs/{cog_name}/coglets/{coglet_name}/meta.json"


def _coglet_log_key(cog_name: str, coglet_name: str) -> str:
    return f"cogs/{cog_name}/coglets/{coglet_name}/log"


def write_file_tree(store: FileStore, cog_name: str, coglet_name: str, branch: str, files: dict[str, str]) -> None:
    pfx = _coglet_prefix(cog_name, coglet_name, branch)
    for rel_path, content in files.items():
        store.upsert(pfx + rel_path, content)


def read_file_tree(store: FileStore, cog_name: str, coglet_name: str, branch: str) -> dict[str, str]:
    pfx = _coglet_prefix(cog_name, coglet_name, branch)
    result: dict[str, str] = {}
    for f in store.list_files(prefix=pfx):
        content = store.get_content(f.key)
        if content is not None:
            result[f.key[len(pfx):]] = content
    return result


def delete_file_tree(store: FileStore, cog_name: str, coglet_name: str, branch: str) -> int:
    pfx = _coglet_prefix(cog_name, coglet_name, branch)
    files = store.list_files(prefix=pfx)
    for f in files:
        store.delete(f.key)
    return len(files)


def load_coglet_meta(store: FileStore, cog_name: str, coglet_name: str) -> CogletMeta | None:
    content = store.get_content(_coglet_meta_key(cog_name, coglet_name))
    if content is None:
        return None
    return CogletMeta.model_validate_json(content)


def save_coglet_meta(store: FileStore, cog_name: str, coglet_name: str, meta: CogletMeta) -> None:
    store.upsert(_coglet_meta_key(cog_name, coglet_name), meta.model_dump_json(indent=2))


def append_coglet_log(store: FileStore, cog_name: str, coglet_name: str, entry: LogEntry) -> None:
    store.append(_coglet_log_key(cog_name, coglet_name), entry.model_dump_json() + "\n")


def read_coglet_log(store: FileStore, cog_name: str, coglet_name: str) -> list[LogEntry]:
    content = store.get_content(_coglet_log_key(cog_name, coglet_name))
    if not content:
        return []
    entries: list[LogEntry] = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if line:
            entries.append(LogEntry.model_validate_json(line))
    return entries


# ---------------------------------------------------------------------------
# CogMeta
# ---------------------------------------------------------------------------

class CogMeta(BaseModel):
    name: str
    created_at: str = Field(default_factory=_now_iso)


def load_cog_meta(store: FileStore, cog_name: str) -> CogMeta | None:
    content = store.get_content(_cog_meta_key(cog_name))
    if content is None:
        return None
    return CogMeta.model_validate_json(content)


def save_cog_meta(store: FileStore, cog_name: str, meta: CogMeta) -> None:
    store.upsert(_cog_meta_key(cog_name), meta.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Coglet — object with code operations
# ---------------------------------------------------------------------------

class CogletError(BaseModel):
    error: str


class CogletInfo(BaseModel):
    cog_name: str
    name: str
    version: int
    test_passed: bool
    test_output: str = ""


class Coglet:
    """A coglet within a cog. Has code operations (propose_patch, read_file, etc.)."""

    def __init__(self, repo, cog_name: str, coglet_name: str) -> None:
        self._repo = repo
        self.cog_name = cog_name
        self.name = coglet_name

    def _store(self) -> FileStore:
        return FileStore(self._repo)

    def _load_meta(self) -> CogletMeta | None:
        return load_coglet_meta(self._store(), self.cog_name, self.name)

    def _save_meta(self, meta: CogletMeta) -> None:
        save_coglet_meta(self._store(), self.cog_name, self.name, meta)

    # -- Patch workflow --

    def propose_patch(self, diff: str) -> "PatchResult | CogletError":
        store = self._store()
        meta = self._load_meta()
        if meta is None:
            return CogletError(error=f"Coglet '{self.name}' not found in cog '{self.cog_name}'")

        main_files = read_file_tree(store, self.cog_name, self.name, "main")
        try:
            patched_files = apply_diff(main_files, diff)
        except ValueError as e:
            return CogletError(error=f"Failed to apply diff: {e}")

        patch_id = str(uuid4())
        write_file_tree(store, self.cog_name, self.name, f"patches/{patch_id}", patched_files)

        result = run_tests(meta.test_command, patched_files, timeout_seconds=meta.timeout_seconds)

        patch_info = PatchInfo(base_version=meta.version, test_passed=result.passed, test_output=result.output)
        meta.patches[patch_id] = patch_info
        self._save_meta(meta)

        append_coglet_log(store, self.cog_name, self.name,
                          LogEntry(action="proposed", patch_id=patch_id, version=meta.version,
                                   test_passed=result.passed, test_output=result.output))

        return PatchResult(patch_id=patch_id, base_version=meta.version,
                           test_passed=result.passed, test_output=result.output)

    def merge_patch(self, patch_id: str) -> "MergeResult | CogletError":
        store = self._store()
        meta = self._load_meta()
        if meta is None:
            return CogletError(error=f"Coglet '{self.name}' not found")

        patch_info = meta.patches.get(patch_id)
        if patch_info is None:
            return CogletError(error=f"Patch '{patch_id}' not found")
        if not patch_info.test_passed:
            return CogletError(error=f"Patch '{patch_id}' has failing tests")
        if patch_info.base_version != meta.version:
            return MergeResult(merged=False, conflict=True,
                               current_version=meta.version, base_version=patch_info.base_version)

        patch_files = read_file_tree(store, self.cog_name, self.name, f"patches/{patch_id}")
        if not patch_files:
            return CogletError(error=f"Patch '{patch_id}' has no files")

        delete_file_tree(store, self.cog_name, self.name, "main")
        write_file_tree(store, self.cog_name, self.name, "main", patch_files)

        meta.version += 1
        del meta.patches[patch_id]
        self._save_meta(meta)
        delete_file_tree(store, self.cog_name, self.name, f"patches/{patch_id}")

        append_coglet_log(store, self.cog_name, self.name,
                          LogEntry(action="merged", patch_id=patch_id, version=meta.version))
        return MergeResult(merged=True, new_version=meta.version)

    def discard_patch(self, patch_id: str) -> "DiscardResult | CogletError":
        store = self._store()
        meta = self._load_meta()
        if meta is None:
            return CogletError(error=f"Coglet '{self.name}' not found")
        if patch_id not in meta.patches:
            return CogletError(error=f"Patch '{patch_id}' not found")

        delete_file_tree(store, self.cog_name, self.name, f"patches/{patch_id}")
        del meta.patches[patch_id]
        self._save_meta(meta)

        append_coglet_log(store, self.cog_name, self.name,
                          LogEntry(action="discarded", patch_id=patch_id))
        return DiscardResult(discarded=True, patch_id=patch_id)

    # -- File access --

    def read_file(self, path: str, patch_id: str | None = None) -> str | CogletError:
        store = self._store()
        branch = f"patches/{patch_id}" if patch_id else "main"
        files = read_file_tree(store, self.cog_name, self.name, branch)
        if path not in files:
            return CogletError(error=f"File '{path}' not found in {branch}")
        return files[path]

    def list_files(self, patch_id: str | None = None) -> list[str]:
        store = self._store()
        branch = f"patches/{patch_id}" if patch_id else "main"
        files = read_file_tree(store, self.cog_name, self.name, branch)
        return sorted(files.keys())

    def list_patches(self) -> list["PatchSummary"]:
        meta = self._load_meta()
        if meta is None:
            return []
        return [
            PatchSummary(patch_id=pid, base_version=p.base_version,
                         test_passed=p.test_passed, test_output=p.test_output, created_at=p.created_at)
            for pid, p in meta.patches.items()
        ]

    def get_status(self) -> "CogletStatus | CogletError":
        meta = self._load_meta()
        if meta is None:
            return CogletError(error=f"Coglet '{self.name}' not found")
        return CogletStatus(cog_name=self.cog_name, name=meta.name,
                            version=meta.version, patch_count=len(meta.patches))

    def run_tests(self) -> "TestResultInfo | CogletError":
        store = self._store()
        meta = self._load_meta()
        if meta is None:
            return CogletError(error=f"Coglet '{self.name}' not found")

        main_files = read_file_tree(store, self.cog_name, self.name, "main")
        result = run_tests(meta.test_command, main_files, timeout_seconds=meta.timeout_seconds)

        append_coglet_log(store, self.cog_name, self.name,
                          LogEntry(action="tests_run", test_passed=result.passed, test_output=result.output))
        return TestResultInfo(passed=result.passed, output=result.output)

    def get_log(self) -> list[LogEntry]:
        return read_coglet_log(self._store(), self.cog_name, self.name)

    def __repr__(self) -> str:
        return f"<Coglet {self.cog_name}/{self.name}>"


# ---------------------------------------------------------------------------
# IO Models for Coglet operations
# ---------------------------------------------------------------------------

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
    cog_name: str
    name: str
    version: int
    patch_count: int


class TestResultInfo(BaseModel):
    passed: bool
    output: str
