"""Daily digest program — summarizes recent events."""

from mind.program import CogentMindProgram

config = CogentMindProgram(
    name="digest",
    program_type="python",
    includes=["identity", "recent-events"],
    tools=["memory get", "event list"],
    triggers=[
        {"pattern": "cron.daily-digest", "priority": 5},
    ],
    metadata={"description": "Summarize recent events into a digest"},
)


def run(context: dict) -> str:
    """Generate a daily digest from recent events."""
    events = context.get("events", [])
    if not events:
        return "No recent events to summarize."
    summary_parts = [f"- {e['type']}: {e.get('source', 'unknown')}" for e in events]
    return "Daily Digest:\n" + "\n".join(summary_parts)
