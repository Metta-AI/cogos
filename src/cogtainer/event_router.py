"""EventRouter — runtime-agnostic event matching and dispatch planning.

Extracts the trigger-matching logic from the orchestrator Lambda into a
reusable module that works with any CogtainerRuntime.
"""

from __future__ import annotations

import logging

from cogtainer.db.protocol import CogtainerRepositoryInterface
from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)


def match_pattern(pattern: str, event_type: str) -> bool:
    """Match event type against trigger pattern. Supports * glob at end."""
    if pattern.endswith("*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


class EventRouter:
    """Match incoming events against triggers and plan dispatches."""

    def __init__(self, repo: CogtainerRepositoryInterface, runtime: CogtainerRuntime) -> None:
        self._repo = repo
        self._runtime = runtime

    def route_event(
        self, event_type: str, source: str, payload: dict
    ) -> list[dict]:
        """Match event against triggers, return list of programs to dispatch.

        Returns dicts with: program_name, trigger_id, payload, runner.
        Does NOT dispatch -- caller spawns executors.
        """
        # 1. Load triggers from repo (enabled only)
        triggers = self._repo.list_triggers(enabled_only=True)

        # 2. Match against event_type
        matched = [t for t in triggers if match_pattern(t.event_pattern, event_type)]
        if not matched:
            logger.info("No triggers matched event type %s", event_type)
            return []

        dispatch_list: list[dict] = []

        for trigger in matched:
            # 3. Cascade guard: skip if source == trigger.program_name
            if source and source == trigger.program_name:
                logger.info("Skipping cascade: %s triggered by itself", trigger.program_name)
                continue

            # 4. Throttle check: if trigger.config.max_events > 0, call repo.throttle_check
            max_events = trigger.config.max_events
            if max_events > 0:
                result = self._repo.throttle_check(
                    trigger.id, max_events, trigger.config.throttle_window_seconds
                )
                if not result.allowed:
                    logger.info("Throttled trigger %s for %s", trigger.id, trigger.program_name)
                    continue

            # 5. Verify program exists via repo.get_program
            program = self._repo.get_program(trigger.program_name)
            if not program:
                logger.warning("Program not found: %s", trigger.program_name)
                continue

            # 6. Determine runner
            runner = payload.get("runner") or program.runner or "lambda"

            dispatch_list.append(
                {
                    "program_name": trigger.program_name,
                    "trigger_id": str(trigger.id),
                    "payload": payload,
                    "runner": runner,
                }
            )

        logger.info(
            "Matched %d/%d triggers for event %s",
            len(dispatch_list),
            len(matched),
            event_type,
        )
        return dispatch_list
