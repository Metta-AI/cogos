"""LocalRuntime — run cogents on the local filesystem."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cogos.db.protocol import CogosRepositoryInterface
    from cogos.runtime.local_ingress_queue import LocalIngressQueue

from cogtainer.config import CogtainerEntry
from cogtainer.llm.provider import LLMProvider
from cogtainer.runtime.base import CogtainerRuntime
from cogtainer.secrets import SecretsProvider

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

        from cogos.runtime.local_ingress_queue import LocalIngressQueue

        self._ingress_queue = LocalIngressQueue()

        from cogtainer.secrets import LocalSecretsProvider

        self._secrets = LocalSecretsProvider(data_dir=str(self._data_dir))

    @property
    def ingress_queue(self) -> LocalIngressQueue:
        return self._ingress_queue

    # ── Repository ───────────────────────────────────────────

    def get_repository(self, cogent_name: str) -> Any:
        from cogos.db.sqlite_repository import SqliteRepository

        cogent_dir = self._data_dir / cogent_name
        cogent_dir.mkdir(parents=True, exist_ok=True)
        return SqliteRepository(
            data_dir=str(cogent_dir),
            ingress_queue_url="local://ingress",
            nudge_callback=self._ingress_queue.send,
        )

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
        llm_provider = self._entry.llm.provider
        env = {
            **os.environ,
            "COGTAINER": self._entry.type,
            "COGENT": cogent_name,
            "USE_LOCAL_DB": "1",
            "SECRETS_PROVIDER": "local",
            "SECRETS_DATA_DIR": str(self._data_dir),
            "LLM_PROVIDER": llm_provider,
            "AWS_REGION": self._entry.region or "us-east-1",
        }
        log_dir = cogent_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "executor.log"
        log_fh = open(log_path, "a")  # noqa: SIM115
        proc = subprocess.Popen(
            [sys.executable, "-m", "cogos.executor", process_id],
            env=env,
            stdout=log_fh,
            stderr=log_fh,
        )
        log_fh.close()
        self._child_procs.append((proc, process_id))

    def reap_dead_executors(self, repo: CogosRepositoryInterface) -> int:
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

    def get_secrets_provider(self) -> SecretsProvider:
        return self._secrets

    def destroy_cogent(self, name: str) -> None:
        cogent_dir = self._data_dir / name
        if cogent_dir.exists():
            shutil.rmtree(cogent_dir)

    # ── Queue messaging ──────────────────────────────────────

    def send_queue_message(self, queue_name: str, body: str, *, dedup_id: str | None = None) -> None:
        logger.info("local queue message [%s]: %s", queue_name, body[:200])

    def get_queue_url(self, queue_name: str) -> str:
        return f"local://{queue_name}"

    # ── Blob URLs + email ────────────────────────────────────

    def get_file_url(self, cogent_name: str, key: str, expires_in: int = 604800) -> str:
        path = self._data_dir / cogent_name / "files" / key
        return f"file://{path}"

    def send_email(self, *, source: str, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        logger.info("local email [%s -> %s]: %s", source, to, subject)
        import uuid
        return str(uuid.uuid4())

    def verify_email_domain(self, domain: str) -> bool:
        return True

    def get_bedrock_client(self) -> Any:
        if self._entry.llm and self._entry.llm.provider == "bedrock":
            import boto3
            return boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return None

    def get_session(self) -> Any:
        return None

    def get_dynamodb_resource(self, region: str | None = None) -> Any:
        return None

    def get_sqs_client(self, region: str | None = None) -> Any:
        return None

    def get_s3_client(self, region: str | None = None) -> Any:
        return None

    def get_ecs_client(self, region: str | None = None) -> Any:
        return None

    def get_rds_data_client(self, region: str | None = None) -> Any:
        return None
