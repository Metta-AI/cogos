"""Local executor daemon — registers with the dashboard, heartbeats, polls for work, and executes."""

from __future__ import annotations

import hashlib
import logging
import secrets
import signal
import threading
from uuid import UUID

from cogos.db.models import ExecutorStatus, ExecutorToken, Run, RunStatus
from cogos.db.models.executor import Executor
from cogos.executor.handler import ExecutorConfig, get_config
from cogos.runtime.dispatch import build_dispatch_event
from cogos.runtime.local import run_and_complete

logger = logging.getLogger(__name__)

_DEFAULT_HEARTBEAT_S = 15
_DEFAULT_POLL_S = 2.0


class ExecutorDaemon:
    """Long-lived local executor that registers and heartbeats with the repo directly."""

    def __init__(
        self,
        repo,
        executor_id: str,
        *,
        executor_tags: list[str] | None = None,
        config: ExecutorConfig | None = None,
        heartbeat_s: float = _DEFAULT_HEARTBEAT_S,
        poll_s: float = _DEFAULT_POLL_S,
    ):
        self.repo = repo
        self.executor_id = executor_id
        self.executor_tags = executor_tags or ["python"]
        self.config = config or get_config()
        self.heartbeat_s = heartbeat_s
        self.poll_s = poll_s

        self._stop = threading.Event()
        self._current_run_id: UUID | None = None
        self._status = ExecutorStatus.IDLE

    # ── Lifecycle ────────────────────────────────────────────

    def register(self) -> None:
        """Register this executor with the local repo."""
        executor = Executor(
            executor_id=self.executor_id,
            channel_type="claude-code",
            executor_tags=self.executor_tags,
            dispatch_type="channel",
            metadata={"daemon": True, "pid": __import__("os").getpid()},
        )
        self.repo.register_executor(executor)
        logger.info("Registered executor %s", self.executor_id)

    def _ensure_token(self) -> None:
        """Ensure at least one executor token exists (needed for dashboard API)."""
        tokens = self.repo.list_executor_tokens()
        if not tokens:
            raw = secrets.token_urlsafe(32)
            token = ExecutorToken(
                name="local-daemon",
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            )
            self.repo.create_executor_token(token)
            logger.info("Created executor token 'local-daemon'")

    def _heartbeat(self) -> None:
        """Send a heartbeat to the repo.

        Only send our local status/run_id when we're actively busy.
        When idle, read the executor's current state so we don't clobber
        a BUSY status that the scheduler just set.
        """
        if self._status == ExecutorStatus.BUSY:
            # We're executing — assert our state
            self.repo.heartbeat_executor(
                self.executor_id,
                status=ExecutorStatus.BUSY,
                current_run_id=self._current_run_id,
            )
        else:
            # Just bump the timestamp, preserve scheduler-assigned status
            e = self.repo.get_executor(self.executor_id)
            if e:
                self.repo.heartbeat_executor(
                    self.executor_id,
                    status=e.status,
                    current_run_id=e.current_run_id,
                )

    def _heartbeat_loop(self) -> None:
        """Background thread that heartbeats at regular intervals."""
        while not self._stop.wait(self.heartbeat_s):
            try:
                self._heartbeat()
            except Exception:
                logger.debug("heartbeat error", exc_info=True)

    # ── Work polling ─────────────────────────────────────────

    def _poll_for_work(self) -> bool:
        """Check if this executor has been assigned a run. Returns True if work was found and executed."""
        executor = self.repo.get_executor(self.executor_id)
        if not executor:
            return False

        if executor.status != ExecutorStatus.BUSY or not executor.current_run_id:
            return False

        run_id = executor.current_run_id
        run = self.repo.get_run(run_id)
        if not run or run.status != RunStatus.RUNNING:
            # Stale assignment — reset to idle
            self.repo.update_executor_status(self.executor_id, ExecutorStatus.IDLE)
            return False

        process = self.repo.get_process(run.process)
        if not process:
            logger.error("Process not found for run %s", run_id)
            self.repo.complete_run(run_id, status=RunStatus.FAILED, error="process not found")
            self.repo.update_executor_status(self.executor_id, ExecutorStatus.IDLE)
            return False

        self._execute(process, run)
        return True

    def _execute(self, process, run: Run) -> None:
        """Execute a dispatched run."""
        self._current_run_id = run.id
        self._status = ExecutorStatus.BUSY
        self._heartbeat()

        logger.info("Executing process=%s run=%s", process.name, run.id)

        event_data: dict = {}
        if run.message:
            from cogos.capabilities.scheduler import DispatchResult
            dispatch = DispatchResult(
                run_id=str(run.id),
                process_id=str(process.id),
                process_name=process.name,
                message_id=str(run.message),
            )
            event_data = build_dispatch_event(self.repo, dispatch)

        try:
            run_and_complete(process, event_data, run, self.config, self.repo)
        except Exception:
            logger.exception("Execution failed for process %s", process.name)

        # Release executor
        self._current_run_id = None
        self._status = ExecutorStatus.IDLE
        self.repo.update_executor_status(self.executor_id, ExecutorStatus.IDLE)
        self._heartbeat()

        logger.info("Finished process=%s run=%s", process.name, run.id)

    # ── Main loop ────────────────────────────────────────────

    def run(self) -> None:
        """Run the daemon: register, heartbeat, and poll for work until stopped."""
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        self._ensure_token()
        self.register()

        # Start heartbeat thread
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb_thread.start()

        # Handle signals
        def _shutdown(signum, frame):
            logger.info("Received signal %s, shutting down", signum)
            self._stop.set()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        logger.info(
            "Daemon running: executor=%s tags=%s poll=%.1fs heartbeat=%.1fs",
            self.executor_id, self.executor_tags, self.poll_s, self.heartbeat_s,
        )

        while not self._stop.is_set():
            try:
                if self._poll_for_work():
                    continue  # Check for more work immediately
            except Exception:
                logger.exception("poll error")
            self._stop.wait(self.poll_s)

        # Cleanup
        logger.info("Daemon stopping, marking executor stale")
        try:
            self.repo.update_executor_status(self.executor_id, ExecutorStatus.STALE)
        except Exception:
            pass
