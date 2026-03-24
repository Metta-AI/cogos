"""Entry point for ``python -m cogos.executor <process_id>``."""

from __future__ import annotations

import logging
import os
import sys
from uuid import UUID

from cogos.db.models import RunStatus
from cogos.executor.handler import get_config
from cogos.runtime.dispatch import build_dispatch_event
from cogos.runtime.local import run_and_complete

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m cogos.executor <process_id>", file=sys.stderr)
        sys.exit(1)

    process_id = UUID(sys.argv[1])
    config = get_config()

    from cogtainer.runtime.factory import create_executor_runtime

    runtime = create_executor_runtime()
    cogent_name = os.environ.get("COGENT", "")
    if cogent_name:
        repo = runtime.get_repository(cogent_name)
    else:
        from cogos.db.factory import create_repository
        repo = create_repository(
            resource_arn=config.db_cluster_arn,
            secret_arn=config.db_secret_arn,
            database=config.db_name,
            region=config.region,
        )

    process = repo.get_process(process_id)
    if not process:
        logger.error("Process not found: %s", process_id)
        sys.exit(1)

    runs = [r for r in repo.list_runs(process_id=process_id) if r.status == RunStatus.RUNNING]
    if not runs:
        logger.error("No RUNNING run found for process %s", process.name)
        sys.exit(1)
    run = runs[0]

    event_data: dict = {}
    if run.message:
        from cogos.capabilities.scheduler import DispatchResult

        dispatch = DispatchResult(
            run_id=str(run.id),
            process_id=str(process_id),
            process_name=process.name,
            message_id=str(run.message),
        )
        event_data = build_dispatch_event(repo, dispatch)

    try:
        run_and_complete(process, event_data, run, config, repo)
    except Exception:
        logger.exception("Executor failed for process %s", process.name)
        sys.exit(1)
    finally:
        from cogos.db.models import ExecutorStatus
        try:
            repo.update_executor_status("local-daemon", ExecutorStatus.IDLE)
        except Exception:
            pass


if __name__ == "__main__":
    main()
