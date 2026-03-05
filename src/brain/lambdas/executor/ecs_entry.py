"""ECS Fargate entry point — runs programs via Claude Code CLI with S3 session sync."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from uuid import UUID

from brain.db.models import Event, Run, RunStatus
from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.events import put_event
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()

CLAUDE_DIR = os.path.expanduser("~/.claude")
WORKSPACE_DIR = "/tmp/workspace"
SYNC_INTERVAL_S = 30


def s3_sync_down(bucket: str, session_id: str) -> None:
    """Download a Claude Code session from S3."""
    prefix = f"s3://{bucket}/sessions/{session_id}/.claude/"
    logger.info(f"Restoring session {session_id} from {prefix}")
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    subprocess.run(
        ["aws", "s3", "sync", prefix, CLAUDE_DIR + "/", "--size-only"],
        capture_output=True,
        timeout=120,
    )


def s3_sync_up(bucket: str, session_id: str) -> None:
    """Upload the Claude Code session to S3."""
    if not os.path.isdir(CLAUDE_DIR):
        return
    prefix = f"s3://{bucket}/sessions/{session_id}/.claude/"
    subprocess.run(
        ["aws", "s3", "sync", CLAUDE_DIR + "/", prefix, "--size-only"],
        capture_output=True,
        timeout=120,
    )


def start_periodic_sync(bucket: str, session_id: str) -> subprocess.Popen | None:
    """Start a background process that syncs to S3 every SYNC_INTERVAL_S seconds."""
    script = (
        f"while true; do sleep {SYNC_INTERVAL_S}; "
        f"aws s3 sync {CLAUDE_DIR}/ s3://{bucket}/sessions/{session_id}/.claude/ --size-only "
        f"2>/dev/null || true; done"
    )
    return subprocess.Popen(["bash", "-c", script])


def main() -> None:
    """Parse payload from env, execute program via Claude Code CLI."""
    payload_json = os.environ.get("EXECUTOR_PAYLOAD", "{}")
    payload = json.loads(payload_json)

    config = get_config()
    repo = get_repo()

    trigger_data = payload.get("trigger", {})
    event_data = payload.get("event", {})
    program_name = trigger_data.get("program_name", "")

    logger.info(f"ECS executor starting for program: {program_name}")

    # Session management: env var > payload > empty (will use run_id later)
    session_id = os.environ.get("CLAUDE_CODE_SESSION", "") or payload.get("session_id", "")
    restored_session = False

    # Restore session from S3 if we have a session_id
    if session_id and config.sessions_bucket:
        s3_sync_down(config.sessions_bucket, session_id)
        restored_session = True

    # Load program
    program = repo.get_program(program_name)
    if not program:
        logger.error(f"Program not found: {program_name}")
        sys.exit(1)

    # Extract task context from payload
    task_data = payload.get("task", {})
    task_id = task_data.get("id")
    task_content = task_data.get("content", "")
    task_memory_keys = task_data.get("memory_keys", [])
    task_tools = task_data.get("tools", [])
    clear_context = task_data.get("clear_context", False)

    # Create run record
    run = Run(
        program_name=program_name,
        trigger_id=trigger_data.get("id"),
        status=RunStatus.RUNNING,
        model_version="claude-code",
    )
    if task_id:
        run.task_id = UUID(task_id)
    run_id = repo.insert_run(run)
    logger.info(f"Created run {run_id}")

    # Session management: task_id for continuity unless clear_context
    if task_id and not clear_context:
        session_id = session_id or task_id
    # Use session_id from env or fall back to run_id
    if not session_id:
        session_id = str(run_id)

    # Start periodic S3 sync
    sync_proc = None
    if config.sessions_bucket:
        sync_proc = start_periodic_sync(config.sessions_bucket, session_id)

    start_time = time.time()

    try:
        # Merge tools from program and task
        all_tools = list(set((program.tools or []) + task_tools))

        # Build Claude Code CLI command
        cmd = ["claude"]

        model = program.model_version or "sonnet"
        cmd.extend(["--model", model])

        if all_tools:
            cmd.extend(["--allowedTools", ",".join(all_tools)])

        # Resume existing session or start fresh
        if restored_session:
            cmd.append("--resume")

        # Build prompt: program content + task content + event context
        prompt = program.content
        if task_content:
            prompt += f"\n\n{task_content}"
        if event_data.get("payload"):
            prompt += f"\n\nEvent context:\n{json.dumps(event_data['payload'], indent=2)}"

        cmd.extend(["--prompt", prompt])

        # Set working directory
        os.makedirs(WORKSPACE_DIR, exist_ok=True)

        logger.info(f"Running Claude Code CLI: {cmd[0]} --model {model}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.ecs_timeout_s if hasattr(config, "ecs_timeout_s") else 3600,
            cwd=WORKSPACE_DIR,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if result.returncode == 0:
            run.status = RunStatus.COMPLETED
            logger.info(f"Run {run_id} completed in {duration_ms}ms")
        else:
            run.status = RunStatus.FAILED
            run.error = result.stderr[:4000] if result.stderr else f"Exit code {result.returncode}"
            logger.error(f"Run {run_id} failed: {run.error}")

        run.duration_ms = duration_ms
        run.completed_at = datetime.now(timezone.utc)
        repo.update_run(run)

        # Emit event
        if run.status == RunStatus.COMPLETED:
            event_type = f"program:completed:{program_name}"
        else:
            event_type = f"program:failed:{program_name}"
        put_event(
            Event(
                event_type=event_type,
                source=program_name,
                payload={"run_id": str(run.id), "duration_ms": duration_ms},
                parent_event_id=event_data.get("id"),
            ),
            config.event_bus_name,
        )

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start_time) * 1000)
        run.status = RunStatus.TIMEOUT
        run.error = "Claude Code CLI timed out"
        run.duration_ms = duration_ms
        run.completed_at = datetime.now(timezone.utc)
        repo.update_run(run)
        logger.error(f"Run {run_id} timed out after {duration_ms}ms")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        run.status = RunStatus.FAILED
        run.error = str(e)[:4000]
        run.duration_ms = duration_ms
        run.completed_at = datetime.now(timezone.utc)
        repo.update_run(run)
        logger.error(f"Run {run_id} failed: {e}")

    finally:
        # Final S3 sync before exit
        if config.sessions_bucket:
            logger.info(f"Final session sync to S3 for {session_id}")
            s3_sync_up(config.sessions_bucket, session_id)

        # Stop periodic sync
        if sync_proc:
            sync_proc.terminate()
            sync_proc.wait(timeout=5)

    if run.status in (RunStatus.TIMEOUT, RunStatus.FAILED):
        sys.exit(1)


if __name__ == "__main__":
    main()
