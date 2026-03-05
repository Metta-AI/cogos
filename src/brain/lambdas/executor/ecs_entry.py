"""ECS Fargate entry point — runs programs via Claude Code CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from brain.db.models import Event, Run, RunStatus
from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.events import put_event
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()


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

    # Load program
    program = repo.get_program(program_name)
    if not program:
        logger.error(f"Program not found: {program_name}")
        sys.exit(1)

    # Create run record
    run = Run(
        program_name=program_name,
        trigger_id=trigger_data.get("id"),
        status=RunStatus.RUNNING,
        model_version="claude-code",
    )
    run_id = repo.insert_run(run)
    logger.info(f"Created run {run_id}")

    start_time = time.time()

    try:
        # Build Claude Code CLI command
        cmd = ["claude"]

        model = program.model_version or "sonnet"
        cmd.extend(["--model", model])

        if program.tools:
            cmd.extend(["--allowedTools", ",".join(program.tools)])

        # Build prompt with event context
        prompt = program.content
        if event_data.get("payload"):
            prompt += f"\n\nEvent context:\n{json.dumps(event_data['payload'], indent=2)}"

        cmd.extend(["--prompt", prompt])

        # Set working directory
        workdir = os.path.join(config.efs_path, "workspace")
        os.makedirs(workdir, exist_ok=True)

        logger.info(f"Running Claude Code CLI: {cmd[0]} --model {model}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config.ecs_timeout_s if hasattr(config, "ecs_timeout_s") else 3600,
            cwd=workdir,
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
        sys.exit(1)

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        run.status = RunStatus.FAILED
        run.error = str(e)[:4000]
        run.duration_ms = duration_ms
        run.completed_at = datetime.now(timezone.utc)
        repo.update_run(run)
        logger.error(f"Run {run_id} failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
