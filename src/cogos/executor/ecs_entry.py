"""ECS task entrypoint — parses dispatch event and calls the executor handler."""

from __future__ import annotations

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    event_json = os.environ.get("DISPATCH_EVENT")
    if not event_json:
        logger.error("DISPATCH_EVENT not set")
        sys.exit(1)

    event = json.loads(event_json)
    logger.info("ECS executor starting: process_id=%s run_id=%s", event.get("process_id"), event.get("run_id"))

    from cogos.executor.handler import handler

    result = handler(event)
    status = result.get("statusCode", 500)
    if status != 200:
        logger.error("Executor failed: %s", result.get("error"))
        sys.exit(1)

    logger.info("Executor completed: run_id=%s", result.get("run_id"))


if __name__ == "__main__":
    main()
