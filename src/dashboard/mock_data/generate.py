"""Generate realistic mock data and write it to the LocalRepository JSON store.

Usage:
    python -m dashboard.mock_data.generate          # writes to ~/.cogent/local/data.json
    python -m dashboard.mock_data.generate /tmp/out  # writes to /tmp/out/data.json
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from brain.db.models import (
    Alert,
    AlertSeverity,
    Channel,
    ChannelType,
    Conversation,
    ConversationStatus,
    Cron,
    Event,
    Memory,
    MemoryVersion,
    Program,
    ProgramType,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Tool,
    Trace,
    Trigger,
    TriggerConfig,
)

NOW = datetime.utcnow()


def _ago(**kw: int) -> datetime:
    return NOW - timedelta(**kw)


# ── Tools (load from disk) ───────────────────────────────

def make_tools() -> list[Tool]:
    """Load real tool definitions from eggs/ovo/tools/."""
    # Find the project root (navigate up from this file)
    project_root = Path(__file__).resolve().parents[3]
    tools_dir = project_root / "eggs" / "ovo" / "tools"

    if tools_dir.is_dir():
        from mind.tool_loader import load_tools_dir
        return load_tools_dir(tools_dir)

    # Fallback: hardcoded tool defs if eggs/ not found
    return [
        Tool(name="mind/memory/get", description="Retrieve a memory value by key name.",
             handler="brain.tools.handlers:memory_get",
             input_schema={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}),
        Tool(name="mind/memory/put", description="Store a value in memory under a key name.",
             handler="brain.tools.handlers:memory_put",
             input_schema={"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}}, "required": ["key", "value"]}),
        Tool(name="mind/event/send", description="Send an event to the event bus.",
             handler="brain.tools.handlers:event_send",
             input_schema={"type": "object", "properties": {"event_type": {"type": "string"}}, "required": ["event_type"]}),
        Tool(name="channels/gmail/check", description="Check Gmail inbox for messages.",
             handler="brain.tools.handlers:gmail_check",
             input_schema={"type": "object", "properties": {"query": {"type": "string"}}}),
        Tool(name="channels/gmail/send", description="Send an email via Gmail.",
             handler="brain.tools.handlers:gmail_send",
             input_schema={"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}),
    ]


# ── Memory ───────────────────────────────────────────────

MEMORY_DEFS = [
    ("cogent", "brand-voice", "Maintain a professional but approachable tone. Use active voice. Avoid jargon unless writing for a technical audience."),
    ("cogent", "code-standards", "All Python code must pass ruff and mypy --strict. Max line length 120. Prefer explicit imports."),
    ("cogent", "alert-thresholds", "CPU: warn at 80%, critical at 95%. Memory: warn at 75%, critical at 90%. Disk: warn at 80%."),
    ("cogent", "email-templates", "Use the standard greeting format: 'Hi {name},' followed by a blank line. Sign off with 'Best regards, Cogent Team'."),
    ("cogent", "issue-triage-rules", "P0: service down or data loss. P1: degraded functionality. P2: cosmetic or minor. P3: feature request."),
    ("polis", "project-context", "Cogent is an AI agent orchestration platform. Key repos: cogents/main, cogents/dashboard. Deploy target: AWS ECS Fargate."),
    ("polis", "team-contacts", "Engineering lead: Alice (alice@example.com). Product: Bob (bob@example.com). DevOps: Charlie (charlie@example.com)."),
    ("cogent", "content-calendar", "Blog posts every Tuesday. Newsletter every other Friday. Social media daily at 10am EST."),
    ("cogent", "faq", "Q: How do I reset my API key? A: Go to Settings > API Keys > Regenerate. Q: What models are supported? A: Claude Sonnet, Haiku, and Opus."),
    ("polis", "deployment-notes", "Last deploy: v1.4.2 on 2025-02-28. Known issue: WebSocket reconnection can take up to 30s after deploy."),
]


def make_memory() -> tuple[list[Memory], list[MemoryVersion]]:
    memories = []
    versions = []
    for source, name, content in MEMORY_DEFS:
        created = _ago(days=random.randint(2, 30))
        mem = Memory(
            id=uuid4(),
            name=name,
            active_version=1,
            created_at=created,
            modified_at=created + timedelta(days=random.randint(0, 5)),
        )
        mv = MemoryVersion(
            id=uuid4(),
            memory_id=mem.id,
            version=1,
            content=content,
            source=source,
            created_at=created,
        )
        memories.append(mem)
        versions.append(mv)
    return memories, versions


# ── Programs ─────────────────────────────────────────────

def make_programs(tool_names: list[str], memory_names: list[str]) -> list[Program]:
    """Create programs referencing real tool and memory names."""
    mind_tools = [t for t in tool_names if t.startswith("mind/")]
    gmail_tools = [t for t in tool_names if t.startswith("channels/gmail")]

    defs = [
        ("triage-issue", ProgramType.PROMPT, "Triage incoming GitHub issues, label and assign.",
         mind_tools, ["issue-triage-rules", "project-context"]),
        ("do-content", ProgramType.PROMPT, "Execute content creation tasks from the task queue.",
         mind_tools, ["brand-voice", "content-calendar"]),
        ("monitor-alerts", ProgramType.PROMPT, "Monitor system health and escalate alerts.",
         mind_tools + gmail_tools, ["alert-thresholds"]),
        ("code-review", ProgramType.PYTHON, "Automated code review for pull requests.",
         mind_tools, ["code-standards"]),
        ("email-responder", ProgramType.PROMPT, "Draft email responses for common inquiries.",
         gmail_tools + mind_tools, ["email-templates", "faq"]),
        ("data-sync", ProgramType.PYTHON, "Synchronize data between external services.",
         mind_tools, []),
    ]

    programs = []
    for name, ptype, content, tools, mem_keys in defs:
        # Only keep memory keys that actually exist
        valid_mem = [k for k in mem_keys if k in memory_names]
        programs.append(Program(
            id=uuid4(),
            name=name,
            tools=tools,
            memory_keys=valid_mem,
            created_at=_ago(days=30),
            updated_at=_ago(days=random.randint(0, 10)),
        ))
    return programs


# ── Channels ─────────────────────────────────────────────

CHANNEL_DEFS = [
    ("general-discord", ChannelType.DISCORD, "1098765432100"),
    ("eng-alerts", ChannelType.DISCORD, "1098765432101"),
    ("github-events", ChannelType.GITHUB, "repo:cogents/main"),
    ("support-inbox", ChannelType.EMAIL, "support@example.com"),
    ("project-board", ChannelType.ASANA, "project-12345"),
    ("local-cli", ChannelType.CLI, None),
]


def make_channels() -> list[Channel]:
    channels = []
    for name, ctype, ext_id in CHANNEL_DEFS:
        channels.append(Channel(
            id=uuid4(),
            type=ctype,
            name=name,
            external_id=ext_id,
            enabled=True,
            config={"webhook_url": f"https://hooks.example.com/{name}"} if ctype == ChannelType.DISCORD else {},
            created_at=_ago(days=25),
        ))
    return channels


# ── Tasks ────────────────────────────────────────────────

def make_tasks(
    programs: list[Program],
    tool_names: list[str],
    memory_names: list[str],
) -> list[Task]:
    """Create tasks referencing valid program names, tool names, and memory keys."""
    prog_map = {p.name: p for p in programs}
    mind_tools = [t for t in tool_names if t.startswith("mind/")]
    gmail_tools = [t for t in tool_names if t.startswith("channels/gmail")]

    defs = [
        ("Review Q1 metrics report", "do-content", TaskStatus.COMPLETED, 10.0,
         "Compile and review Q1 metrics.", mind_tools, ["brand-voice", "content-calendar"]),
        ("Write blog post: AI agents", "do-content", TaskStatus.RUNNING, 8.0,
         "Draft a blog post about AI agent architecture.", mind_tools, ["brand-voice"]),
        ("Triage issue #142", "triage-issue", TaskStatus.COMPLETED, 5.0,
         "Investigate and label the reported bug.", mind_tools, ["issue-triage-rules"]),
        ("Update API documentation", "do-content", TaskStatus.RUNNABLE, 6.0,
         "Refresh API docs for v2 endpoints.", mind_tools, ["project-context"]),
        ("Deploy staging environment", "data-sync", TaskStatus.COMPLETED, 9.0,
         "Deploy latest build to staging.", mind_tools, ["deployment-notes"]),
        ("Monitor weekend alerts", "monitor-alerts", TaskStatus.RUNNING, 7.0,
         "Watch for critical alerts over the weekend.", mind_tools + gmail_tools, ["alert-thresholds"]),
        ("Review PR #87: auth refactor", "code-review", TaskStatus.COMPLETED, 4.0,
         "Review authentication refactor PR.", mind_tools, ["code-standards"]),
        ("Respond to partner inquiry", "email-responder", TaskStatus.RUNNABLE, 3.0,
         "Draft response to partnership email.", gmail_tools + mind_tools, ["email-templates"]),
        ("Sync CRM contacts", "data-sync", TaskStatus.DISABLED, 2.0,
         "Synchronize contacts from CRM to local DB.", mind_tools, []),
        ("Triage issue #155", "triage-issue", TaskStatus.RUNNING, 5.0,
         "New feature request needs labeling.", mind_tools, ["issue-triage-rules"]),
        ("Weekly digest email", "email-responder", TaskStatus.COMPLETED, 1.0,
         "Send weekly project digest.", gmail_tools, ["faq"]),
        ("Code review PR #92", "code-review", TaskStatus.RUNNABLE, 6.0,
         "Review dashboard component changes.", mind_tools, ["code-standards"]),
    ]

    tasks = []
    for i, (name, prog, status, priority, desc, tools, mem_keys) in enumerate(defs):
        created = _ago(days=random.randint(1, 14), hours=random.randint(0, 23))
        updated = created + timedelta(hours=random.randint(1, 48))
        completed = updated + timedelta(hours=random.randint(1, 6)) if status == TaskStatus.COMPLETED else None
        # Only keep memory keys that exist
        valid_mem = [k for k in mem_keys if k in memory_names]
        tasks.append(Task(
            id=uuid4(),
            name=name,
            description=desc,
            program_name=prog,
            status=status,
            priority=priority,
            content=f"Task content for: {name}",
            memory_keys=valid_mem,
            tools=tools,
            recurrent=i % 5 == 0,
            creator="system" if i % 2 == 0 else "user",
            created_at=created,
            updated_at=updated,
            completed_at=completed,
        ))
    return tasks


# ── Runs ─────────────────────────────────────────────────

def make_runs(tasks: list[Task], programs: list[Program], triggers: list[Trigger]) -> list[Run]:
    runs = []
    for task in tasks:
        n_runs = random.randint(1, 4)
        for j in range(n_runs):
            started = (task.created_at or _ago(days=5)) + timedelta(hours=j * 2)
            if task.status == TaskStatus.COMPLETED and j == n_runs - 1:
                status = RunStatus.COMPLETED
            elif task.status == TaskStatus.RUNNING and j == n_runs - 1:
                status = RunStatus.RUNNING
            else:
                status = random.choice([RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.COMPLETED])
            duration = random.randint(5000, 120000) if status != RunStatus.RUNNING else None
            completed = started + timedelta(milliseconds=duration) if duration else None
            runs.append(Run(
                id=uuid4(),
                program_name=task.program_name,
                task_id=task.id,
                trigger_id=random.choice(triggers).id if triggers and random.random() > 0.5 else None,
                status=status,
                tokens_input=random.randint(500, 15000),
                tokens_output=random.randint(200, 8000),
                cost_usd=Decimal(str(round(random.uniform(0.01, 0.50), 4))),
                duration_ms=duration,
                error="Rate limit exceeded" if status == RunStatus.FAILED and random.random() > 0.5 else
                      "Timeout after 120s" if status == RunStatus.FAILED else None,
                model_version="claude-sonnet-4-20250514" if random.random() > 0.3 else "claude-haiku-4-5-20251001",
                started_at=started,
                completed_at=completed,
            ))
    return runs


# ── Triggers ─────────────────────────────────────────────

TRIGGER_DEFS = [
    ("triage-issue", "github.issue.opened", 5),
    ("code-review", "github.pull_request.opened", 5),
    ("monitor-alerts", "system.alert.fired", 1),
    ("email-responder", "email.received", 10),
    ("data-sync", "schedule.daily", 20),
    ("do-content", "task.created", 15),
]


def make_triggers() -> list[Trigger]:
    triggers = []
    for prog, pattern, priority in TRIGGER_DEFS:
        triggers.append(Trigger(
            id=uuid4(),
            program_name=prog,
            event_pattern=pattern,
            priority=priority,
            config=TriggerConfig(retry_max_attempts=2 if priority < 10 else 1),
            enabled=True,
            created_at=_ago(days=20),
        ))
    return triggers


# ── Crons ────────────────────────────────────────────────

CRON_DEFS = [
    ("0 9 * * *", "schedule.daily", True, {"description": "Daily morning sync"}),
    ("0 */6 * * *", "health.check", True, {"description": "Health check every 6 hours"}),
    ("0 0 * * 1", "schedule.weekly", True, {"description": "Weekly Monday digest"}),
    ("30 14 * * 5", "report.weekly", False, {"description": "Friday afternoon report"}),
    ("0 0 1 * *", "schedule.monthly", True, {"description": "Monthly cleanup"}),
]


def make_crons() -> list[Cron]:
    crons = []
    for expr, pattern, enabled, meta in CRON_DEFS:
        crons.append(Cron(
            id=uuid4(),
            cron_expression=expr,
            event_pattern=pattern,
            enabled=enabled,
            metadata=meta,
            created_at=_ago(days=15),
        ))
    return crons


# ── Events ───────────────────────────────────────────────

EVENT_TYPES = [
    "github.issue.opened", "github.issue.closed", "github.pull_request.opened",
    "github.pull_request.merged", "email.received", "email.sent",
    "system.alert.fired", "system.alert.resolved", "task.created",
    "task.completed", "schedule.daily", "health.check",
    "channel.message", "user.login", "deploy.started", "deploy.completed",
]

EVENT_SOURCES = [
    "github-webhook", "email-gateway", "cron-scheduler",
    "system-monitor", "user-action", "api-gateway",
]


def make_events(n: int = 60) -> tuple[list[Event], int]:
    events = []
    for i in range(1, n + 1):
        etype = random.choice(EVENT_TYPES)
        created = _ago(hours=random.randint(0, 72))
        parent = random.choice(events).id if events and random.random() > 0.7 else None
        events.append(Event(
            id=i,
            event_type=etype,
            source=random.choice(EVENT_SOURCES),
            payload=_event_payload(etype),
            parent_event_id=parent,
            created_at=created,
        ))
    events.sort(key=lambda e: e.created_at or datetime.min)
    return events, n


def _event_payload(etype: str) -> dict:
    if "github.issue" in etype:
        return {"issue_number": random.randint(100, 200), "repo": "cogents/main",
                "title": random.choice(["Bug: login fails", "Feature: dark mode", "Perf: slow queries"])}
    if "github.pull_request" in etype:
        return {"pr_number": random.randint(80, 120), "repo": "cogents/main",
                "author": random.choice(["alice", "bob", "charlie"])}
    if "email" in etype:
        return {"from": "partner@example.com", "subject": "Re: Integration proposal"}
    if "system.alert" in etype:
        return {"metric": "cpu_usage", "value": round(random.uniform(70, 99), 1), "threshold": 80}
    if "deploy" in etype:
        return {"environment": random.choice(["staging", "production"]), "version": f"v1.{random.randint(0,9)}.{random.randint(0,20)}"}
    return {"detail": etype}


# ── Conversations ────────────────────────────────────────

def make_conversations(channels: list[Channel]) -> list[Conversation]:
    convs = []
    statuses = [ConversationStatus.ACTIVE, ConversationStatus.ACTIVE,
                ConversationStatus.IDLE, ConversationStatus.CLOSED]
    for i in range(8):
        started = _ago(hours=random.randint(1, 72))
        convs.append(Conversation(
            id=uuid4(),
            context_key=f"conv-{i:03d}",
            channel_id=random.choice(channels).id if channels else None,
            status=random.choice(statuses),
            started_at=started,
            last_active=started + timedelta(minutes=random.randint(5, 300)),
        ))
    return convs


# ── Alerts ───────────────────────────────────────────────

ALERT_DEFS = [
    (AlertSeverity.CRITICAL, "high_cpu", "system-monitor", "CPU usage exceeded 95% on worker-3"),
    (AlertSeverity.WARNING, "slow_query", "db-monitor", "Query took >5s: SELECT * FROM events WHERE..."),
    (AlertSeverity.EMERGENCY, "service_down", "health-check", "API gateway not responding (3 consecutive failures)"),
    (AlertSeverity.WARNING, "rate_limit", "api-gateway", "Rate limit 80% consumed for Claude API"),
    (AlertSeverity.CRITICAL, "memory_leak", "system-monitor", "Memory usage growing steadily on worker-1"),
    (AlertSeverity.WARNING, "cert_expiry", "cert-monitor", "TLS certificate expires in 7 days"),
    (AlertSeverity.WARNING, "disk_space", "system-monitor", "Disk usage at 85% on /data volume"),
]


def make_alerts() -> list[Alert]:
    alerts = []
    for i, (severity, atype, source, message) in enumerate(ALERT_DEFS):
        created = _ago(hours=random.randint(0, 48))
        resolved = created + timedelta(hours=random.randint(1, 6)) if i >= 4 else None
        alerts.append(Alert(
            id=uuid4(),
            severity=severity,
            alert_type=atype,
            source=source,
            message=message,
            metadata={"host": f"worker-{random.randint(1,4)}", "region": "us-east-1"},
            acknowledged_at=created + timedelta(minutes=15) if i % 2 == 0 else None,
            resolved_at=resolved,
            created_at=created,
        ))
    return alerts


# ── Traces ───────────────────────────────────────────────

def make_traces(runs: list[Run], tool_names: list[str]) -> list[Trace]:
    traces = []
    for run in runs:
        if run.status == RunStatus.RUNNING:
            continue
        used_tools = random.sample(tool_names, min(2, len(tool_names))) if tool_names else []
        traces.append(Trace(
            id=uuid4(),
            run_id=run.id,
            tool_calls=[
                {"tool": t, "args": {"key": "example"}, "result": "ok"}
                for t in used_tools
            ] if random.random() > 0.3 else [],
            memory_ops=[
                {"op": "read", "key": "brand-voice"},
            ] if random.random() > 0.5 else [],
            model_version=run.model_version,
            created_at=run.completed_at or run.started_at,
        ))
    return traces


# ── Assemble & Write ─────────────────────────────────────

def generate(data_dir: str | None = None) -> Path:
    """Generate mock data and write to data.json. Returns the file path."""
    from brain.db.local_repository import _json_serial

    if data_dir is None:
        import os
        data_dir = os.environ.get("COGENT_LOCAL_DATA", str(Path.home() / ".cogent" / "local"))

    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "data.json"

    # Build tools and memory first — others reference them by name
    tools = make_tools()
    tool_names = [t.name for t in tools]
    memories, memory_versions = make_memory()
    memory_names = [m.name for m in memories]

    programs = make_programs(tool_names, memory_names)
    channels = make_channels()
    triggers = make_triggers()
    crons = make_crons()
    tasks = make_tasks(programs, tool_names, memory_names)
    runs = make_runs(tasks, programs, triggers)
    events, event_seq = make_events(60)
    conversations = make_conversations(channels)
    alerts = make_alerts()
    traces = make_traces(runs, tool_names)

    data = {
        "programs": [p.model_dump(mode="json") for p in programs],
        "tasks": [t.model_dump(mode="json") for t in tasks],
        "triggers": [t.model_dump(mode="json") for t in triggers],
        "crons": [c.model_dump(mode="json") for c in crons],
        "events": [e.model_dump(mode="json") for e in events],
        "event_seq": event_seq,
        "runs": [r.model_dump(mode="json") for r in runs],
        "conversations": [c.model_dump(mode="json") for c in conversations],
        "channels": [ch.model_dump(mode="json") for ch in channels],
        "alerts": [a.model_dump(mode="json") for a in alerts],
        "traces": [t.model_dump(mode="json") for t in traces],
        "tools": [t.model_dump(mode="json") for t in tools],
        "memories_v2": [m.model_dump(mode="json", exclude={"versions"}) for m in memories],
        "memory_versions": [mv.model_dump(mode="json") for mv in memory_versions],
    }

    out_file.write_text(json.dumps(data, indent=2, default=_json_serial))
    print(f"Wrote mock data to {out_file}")
    print(f"  {len(tools)} tools, {len(programs)} programs, {len(tasks)} tasks, {len(runs)} runs")
    print(f"  {len(triggers)} triggers, {len(crons)} crons, {len(events)} events")
    print(f"  {len(channels)} channels, {len(conversations)} conversations")
    print(f"  {len(alerts)} alerts, {len(memories)} memories, {len(traces)} traces")
    return out_file


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    generate(target)
