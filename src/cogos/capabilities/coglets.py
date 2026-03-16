"""CogletsCapability — CRUD factory for coglets."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.coglet import (
    CogletMeta,
    read_file_tree,
    run_tests,
    write_file_tree,
    delete_file_tree,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class CogletInfo(BaseModel):
    coglet_id: str
    name: str
    version: int
    test_passed: bool
    test_output: str = ""
    test_command: str = ""
    executor: str = "subprocess"


class CogletError(BaseModel):
    error: str


class DeleteResult(BaseModel):
    deleted: bool
    coglet_id: str


# ── Meta helpers (module-level, imported by coglet.py) ────────


def _meta_key(coglet_id: str) -> str:
    return f"coglets/{coglet_id}/meta.json"


def _load_meta(store: FileStore, coglet_id: str) -> CogletMeta | None:
    """Read and parse meta.json for a coglet."""
    content = store.get_content(_meta_key(coglet_id))
    if content is None:
        return None
    return CogletMeta.model_validate_json(content)


def _save_meta(store: FileStore, meta: CogletMeta) -> None:
    """Write meta.json for a coglet."""
    store.upsert(_meta_key(meta.id), meta.model_dump_json(indent=2))


# ── Capability ───────────────────────────────────────────────


class CogletsCapability(Capability):
    """Factory for coglets: create, list, get, delete.

    Usage:
        coglets.create("my-widget", test_command="pytest", files={...})
        coglets.list()
        coglets.get(coglet_id)
        coglets.delete(coglet_id)
    """

    ALL_OPS = {"create", "list", "get", "delete"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        # Ops intersection
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        # coglet_ids intersection
        old_ids = existing.get("coglet_ids")
        new_ids = requested.get("coglet_ids")
        if old_ids is not None and new_ids is not None:
            result["coglet_ids"] = sorted(set(old_ids) & set(new_ids))
        elif old_ids is not None:
            result["coglet_ids"] = old_ids
        elif new_ids is not None:
            result["coglet_ids"] = new_ids
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(
                f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})"
            )
        allowed_ids = self._scope.get("coglet_ids")
        if allowed_ids is not None:
            coglet_id = context.get("coglet_id", "")
            if coglet_id and str(coglet_id) not in allowed_ids:
                raise PermissionError(
                    f"Coglet '{coglet_id}' not permitted; allowed: {allowed_ids}"
                )

    def create(
        self,
        name: str,
        test_command: str,
        files: dict[str, str],
        executor: str = "subprocess",
        timeout_seconds: int = 60,
    ) -> CogletInfo | CogletError:
        """Create a new coglet with initial files and run tests."""
        self._check("create")

        meta = CogletMeta(
            name=name,
            test_command=test_command,
            executor=executor,
            timeout_seconds=timeout_seconds,
        )

        store = FileStore(self.repo)

        # Write files to main branch
        write_file_tree(store, meta.id, "main", files)

        # Run initial tests
        result = run_tests(test_command, files, timeout_seconds=timeout_seconds)

        # Save meta
        _save_meta(store, meta)

        return CogletInfo(
            coglet_id=meta.id,
            name=meta.name,
            version=meta.version,
            test_passed=result.passed,
            test_output=result.output,
            test_command=meta.test_command,
            executor=meta.executor,
        )

    def list(self) -> list[CogletInfo]:
        """List all coglets."""
        self._check("list")
        store = FileStore(self.repo)
        files = store.list_files(prefix="coglets/")
        results: list[CogletInfo] = []
        seen: set[str] = set()
        for f in files:
            if f.key.endswith("/meta.json"):
                # Extract coglet_id from coglets/{id}/meta.json
                parts = f.key.split("/")
                if len(parts) >= 3:
                    coglet_id = parts[1]
                    if coglet_id in seen:
                        continue
                    seen.add(coglet_id)
                    meta = _load_meta(store, coglet_id)
                    if meta is not None:
                        results.append(
                            CogletInfo(
                                coglet_id=meta.id,
                                name=meta.name,
                                version=meta.version,
                                test_passed=True,
                                test_command=meta.test_command,
                                executor=meta.executor,
                            )
                        )
        return results

    def get(self, coglet_id: str) -> CogletInfo | CogletError:
        """Get a coglet by ID."""
        self._check("get", coglet_id=coglet_id)
        store = FileStore(self.repo)
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")
        return CogletInfo(
            coglet_id=meta.id,
            name=meta.name,
            version=meta.version,
            test_passed=True,
            test_command=meta.test_command,
            executor=meta.executor,
        )

    def delete(self, coglet_id: str) -> DeleteResult | CogletError:
        """Delete a coglet and all its files."""
        self._check("delete", coglet_id=coglet_id)
        store = FileStore(self.repo)
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        # Delete all files under coglets/{id}/
        all_files = store.list_files(prefix=f"coglets/{coglet_id}/")
        for f in all_files:
            store.delete(f.key)

        return DeleteResult(deleted=True, coglet_id=coglet_id)

    def __repr__(self) -> str:
        return "<CogletsCapability create() list() get() delete()>"
