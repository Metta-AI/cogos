"""LocalRuntime — run cogents on the local filesystem."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)


class LocalRuntime(CogtainerRuntime):
    """Cogtainer runtime backed by the local filesystem."""

    def __init__(self, entry: CogtainerEntry, llm: LLMProvider) -> None:
        self._entry = entry
        self._llm = llm
        raw = entry.data_dir or str(Path.home() / ".cogos" / "local")
        self._data_dir = Path(os.path.expanduser(os.path.expandvars(raw)))
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._child_procs: list[tuple[subprocess.Popen, str]] = []

        from cogtainer.secrets import LocalSecretsProvider

        self._secrets = LocalSecretsProvider(data_dir=str(self._data_dir))

    # ── Repository ───────────────────────────────────────────

    def get_repository(self, cogent_name: str) -> Any:
        from cogos.db.local_repository import LocalRepository

        cogent_dir = self._data_dir / cogent_name
        cogent_dir.mkdir(parents=True, exist_ok=True)
        return LocalRepository(data_dir=str(cogent_dir))

    # ── LLM ──────────────────────────────────────────────────

    def converse(
        self,
        *,
        messages: list[dict],
        system: list[dict],
        tool_config: dict,
        model: str | None = None,
    ) -> dict:
        return self._llm.converse(
            messages=messages,
            system=system,
            tool_config=tool_config,
            model=model,
        )

    # ── File storage ─────────────────────────────────────────

    def put_file(self, cogent_name: str, key: str, data: bytes) -> str:
        path = self._data_dir / cogent_name / "files" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get_file(self, cogent_name: str, key: str) -> bytes:
        path = self._data_dir / cogent_name / "files" / key
        return path.read_bytes()

    # ── Events ───────────────────────────────────────────────

    def emit_event(self, cogent_name: str, event: dict) -> None:
        logger.info("local event [%s]: %s", cogent_name, event)

    # ── Executor ─────────────────────────────────────────────

    def spawn_executor(self, cogent_name: str, process_id: str) -> None:
        cogent_dir = self._data_dir / cogent_name
        env = {
            **os.environ,
            "COGTAINER": self._entry.type,
            "COGENT": cogent_name,
            "USE_LOCAL_DB": "1",
            "COGOS_LOCAL_DATA": str(cogent_dir),
            "SECRETS_PROVIDER": "local",
            "SECRETS_DATA_DIR": str(self._data_dir),
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "cogos.executor", process_id],
            env=env,
        )
        self._child_procs.append((proc, process_id))

    def reap_dead_executors(self, repo: Any) -> int:
        """Check for executor subprocesses that exited with errors and fail their runs."""
        from cogos.db.models import RunStatus

        alive = []
        failed = 0
        for proc, process_id in self._child_procs:
            rc = proc.poll()
            if rc is None:
                alive.append((proc, process_id))
            elif rc != 0:
                from uuid import UUID

                runs = repo.list_runs(process_id=UUID(process_id), status="running")
                for run in runs:
                    error = f"Executor subprocess exited with code {rc}"
                    repo.complete_run(run.id, status=RunStatus.FAILED, error=error)
                    failed += 1
            # rc == 0: completed successfully, run_and_complete already handled it
        self._child_procs = alive
        return failed

    # ── Cogent lifecycle ─────────────────────────────────────

    def list_cogents(self) -> list[str]:
        if not self._data_dir.exists():
            return []
        return sorted(
            d.name for d in self._data_dir.iterdir() if d.is_dir()
        )

    def create_cogent(self, name: str) -> None:
        cogent_dir = self._data_dir / name
        cogent_dir.mkdir(parents=True, exist_ok=True)
        (cogent_dir / "files").mkdir(exist_ok=True)

    def get_secrets_provider(self):
        return self._secrets

    def destroy_cogent(self, name: str) -> None:
        cogent_dir = self._data_dir / name
        if cogent_dir.exists():
            shutil.rmtree(cogent_dir)
