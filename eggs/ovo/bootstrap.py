"""System bootstrap: cron schedules, triggers, and memory for task execution."""

from mind.bootstrap_loader import CogentCron, CogentMemory, CogentTrigger

cron = [
    CogentCron(
        cron_expression="rate(30 seconds)",
        event_pattern="scheduler:tick",
    ),
]

triggers = [
    CogentTrigger(
        program_name="vsm/s1/pick-task-to-run",
        event_pattern="scheduler:tick",
        priority=1,
    ),
    CogentTrigger(
        program_name="vsm/s1/verify-completion",
        event_pattern="run:succeeded",
        priority=1,
    ),
    CogentTrigger(
        program_name="vsm/s1/handle-run-failure",
        event_pattern="run:failed",
        priority=1,
    ),
]

memory = [
    CogentMemory(
        name="/vsm/s1/task-priority-temperature",
        content="1.0",
    ),
]
