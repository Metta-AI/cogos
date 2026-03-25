"""History capability — run history, file mutations, cross-process audit."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

_RELATIVE_RE = re.compile(r"^(\d+)\s*(s|m|h|d)$")
_UNIT_MAP = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def _resolve_since(since: str) -> str:
    """Convert a relative time string like '5m' to an ISO timestamp.

    Passes through values that don't match the relative pattern (e.g. ISO
    timestamps) unchanged.
    """
    m = _RELATIVE_RE.match(since.strip())
    if m:
        amount = int(m.group(1))
        unit = _UNIT_MAP[m.group(2)]
        cutoff = datetime.now(timezone.utc) - timedelta(**{unit: amount})
        return cutoff.isoformat()
    return since


# ── IO Models ────────────────────────────────────────────────


class RunSummary(BaseModel):
    id: str
    process_id: str
    process_name: str
    status: str
    duration_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: str = "0"
    error: str | None = None
    result: dict | None = None
    model_version: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class FileMutation(BaseModel):
    key: str
    version: int
    created_at: str | None = None


class HistoryError(BaseModel):
    error: str


# ── ProcessHistory handle ────────────────────────────────────


class ProcessHistory:
    """Scoped to a single process's run history."""

    def __init__(self, repo, process) -> None:
        self._repo = repo
        self._process = process
        self._proc_cache: dict[UUID, str] = {process.id: process.name}

    def runs(self, limit: int = 10) -> list[RunSummary]:
        """Recent runs for this process."""
        raw = self._repo.list_runs(process_id=self._process.id, limit=limit)
        return [self._to_summary(r) for r in raw]

    def files(self, run_id: str) -> list[FileMutation]:
        """File versions created by a specific run."""
        raw = self._repo.list_file_mutations(UUID(run_id))
        return [
            FileMutation(
                key=r["key"],
                version=r["version"],
                created_at=str(r["created_at"]) if r.get("created_at") else None,
            )
            for r in raw
        ]

    def _proc_name(self, process_id: UUID) -> str:
        if process_id not in self._proc_cache:
            proc = self._repo.get_process(process_id)
            self._proc_cache[process_id] = proc.name if proc else "unknown"
        return self._proc_cache[process_id]

    def _to_summary(self, run) -> RunSummary:
        return RunSummary(
            id=str(run.id),
            process_id=str(run.process),
            process_name=self._proc_name(run.process),
            status=run.status.value,
            duration_ms=run.duration_ms,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=str(run.cost_usd),
            error=run.error,
            result=run.result,
            model_version=run.model_version,
            created_at=str(run.created_at) if run.created_at else None,
            completed_at=str(run.completed_at) if run.completed_at else None,
        )

    def __repr__(self) -> str:
        return f"<ProcessHistory '{self._process.name}' runs() files()>"


# ── Capability ───────────────────────────────────────────────


class HistoryCapability(Capability):
    """Run history and file mutation audit.

    Usage:
        h = history.process("worker-3")
        h.runs(limit=5)
        h.files(run_id="...")
        history.query(status="failed")
        history.failed(since="1h")
    """

    ALL_OPS = {"query", "process"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {}
        old_ops = set(existing.get("ops", self.ALL_OPS))
        new_ops = set(requested.get("ops", self.ALL_OPS))
        merged["ops"] = sorted(old_ops & new_ops)
        old_pids = set(existing.get("process_ids", []))
        new_pids = set(requested.get("process_ids", []))
        if old_pids and new_pids:
            merged["process_ids"] = sorted(old_pids & new_pids)
        elif old_pids:
            merged["process_ids"] = sorted(old_pids)
        elif new_pids:
            merged["process_ids"] = sorted(new_pids)
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops", self.ALL_OPS))
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed (allowed: {sorted(allowed)})")

    def _check_process_access(self, process_id: UUID) -> bool:
        """Check if scope restricts access to specific process IDs."""
        if not self._scope:
            return True
        allowed_pids = self._scope.get("process_ids")
        if not allowed_pids:
            return True
        return str(process_id) in allowed_pids

    def process(
        self, name: str | None = None, id: str | None = None,
    ) -> ProcessHistory | HistoryError:
        """Get a handle scoped to one process's history."""
        self._check("process")
        if id:
            proc = self.repo.get_process(UUID(id))
        elif name:
            proc = self.repo.get_process_by_name(name)
        else:
            return HistoryError(error="name or id required")

        if proc is None:
            return HistoryError(error="process not found")

        if not self._check_process_access(proc.id):
            return HistoryError(error="access denied for this process")

        return ProcessHistory(self.repo, proc)

    def query(
        self,
        status: str | None = None,
        process_name: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[RunSummary]:
        """Cross-process run query.

        ``since`` accepts relative durations like ``"5m"``, ``"1h"``, ``"30s"``
        as well as ISO-8601 timestamps.
        """
        self._check("query")
        if since:
            since = _resolve_since(since)

        if process_name:
            raw = self.repo.list_runs_by_process_glob(
                process_name, status=status, since=since, limit=limit,
            )
        else:
            raw = self.repo.list_runs(status=status, since=since, limit=limit)

        # Apply process_ids scope filter
        allowed_pids = (self._scope or {}).get("process_ids")
        if allowed_pids:
            pid_set = {UUID(p) for p in allowed_pids}
            raw = [r for r in raw if r.process in pid_set]

        proc_cache: dict[UUID, str] = {}
        results = []
        for run in raw:
            if run.process not in proc_cache:
                proc = self.repo.get_process(run.process)
                proc_cache[run.process] = proc.name if proc else "unknown"
            results.append(RunSummary(
                id=str(run.id),
                process_id=str(run.process),
                process_name=proc_cache[run.process],
                status=run.status.value,
                duration_ms=run.duration_ms,
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
                cost_usd=str(run.cost_usd),
                error=run.error,
                result=run.result,
                model_version=run.model_version,
                created_at=str(run.created_at) if run.created_at else None,
                completed_at=str(run.completed_at) if run.completed_at else None,
            ))
        return results

    def failed(self, since: str | None = None, limit: int = 20) -> list[RunSummary]:
        """Shorthand for query(status="failed", ...)."""
        return self.query(status="failed", since=since, limit=limit)

    def __repr__(self) -> str:
        return "<HistoryCapability process() query() failed()>"
