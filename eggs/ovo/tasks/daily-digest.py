"""Scheduled daily digest task — runs the digest program."""

from mind.task_loader import CogentMindTask

config = CogentMindTask(
    name="daily-digest",
    program_name="digest",
    description="Generate and publish a daily summary of cogent activity",
    tools=["memory get", "event list", "event send"],
    memory_keys=["identity"],
    priority=5.0,
    runner="lambda",
    metadata={"schedule": "daily", "hour": 9},
)
