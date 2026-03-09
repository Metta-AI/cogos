"""Generate realistic CogOS mock data for local development.

Usage:
    python -m dashboard.mock_data.generate_cogos
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from cogos.db.models import (
    Capability,
    Event,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)

NOW = datetime.utcnow()


def _ago(**kw: int) -> datetime:
    return NOW - timedelta(**kw)


def _json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


# ── Capabilities ──────────────────────────────────────────

CAPABILITY_DEFS = [
    ("files/read", "Read a file from the file store", "cogos.capabilities.files:read"),
    ("files/write", "Write or update a file in the file store", "cogos.capabilities.files:write"),
    ("files/list", "List files matching a prefix", "cogos.capabilities.files:list_files"),
    ("procs/spawn", "Spawn a new process", "cogos.capabilities.procs:spawn"),
    ("procs/signal", "Send a signal to a running process", "cogos.capabilities.procs:signal"),
    ("events/emit", "Emit an event to the event bus", "cogos.capabilities.events:emit"),
    ("events/query", "Query recent events", "cogos.capabilities.events:query"),
    ("scheduler/cron", "Schedule a recurring event", "cogos.capabilities.scheduler:cron"),
    ("secrets/get", "Read a secret value", "cogos.capabilities.secrets:get"),
    ("resources/request", "Request a resource allocation", "cogos.capabilities.resources:request"),
]


def make_capabilities() -> list[Capability]:
    caps = []
    for name, desc, handler in CAPABILITY_DEFS:
        caps.append(Capability(
            id=uuid4(),
            name=name,
            description=desc,
            handler=handler,
            enabled=True,
            created_at=_ago(days=30),
            updated_at=_ago(days=random.randint(0, 10)),
        ))
    return caps


# ── Processes ─────────────────────────────────────────────

PROCESS_DEFS = [
    ("triage-issues", ProcessMode.DAEMON, ProcessStatus.RUNNING, 8.0, "lambda",
     "Continuously triage incoming GitHub issues, apply labels and assign owners."),
    ("content-writer", ProcessMode.ONE_SHOT, ProcessStatus.RUNNABLE, 5.0, "lambda",
     "Generate blog posts and documentation from task queue."),
    ("alert-monitor", ProcessMode.DAEMON, ProcessStatus.RUNNING, 9.0, "lambda",
     "Monitor system health metrics and escalate alerts."),
    ("code-reviewer", ProcessMode.ONE_SHOT, ProcessStatus.WAITING, 6.0, "lambda",
     "Automated code review for pull requests."),
    ("email-responder", ProcessMode.ONE_SHOT, ProcessStatus.COMPLETED, 4.0, "lambda",
     "Draft and send email responses to common inquiries."),
    ("data-sync", ProcessMode.ONE_SHOT, ProcessStatus.RUNNABLE, 3.0, "ecs",
     "Synchronize data between external services and local store."),
    ("deploy-manager", ProcessMode.ONE_SHOT, ProcessStatus.WAITING, 7.0, "ecs",
     "Orchestrate staging and production deployments."),
    ("weekly-digest", ProcessMode.ONE_SHOT, ProcessStatus.COMPLETED, 2.0, "lambda",
     "Compile and send the weekly project digest email."),
]


def make_processes() -> list[Process]:
    processes = []
    for name, mode, status, priority, runner, content in PROCESS_DEFS:
        processes.append(Process(
            id=uuid4(),
            name=name,
            mode=mode,
            status=status,
            priority=priority,
            runner=runner,
            content=content,
            model="claude-sonnet-4-20250514" if runner == "lambda" else None,
            preemptible=mode == ProcessMode.ONE_SHOT,
            max_retries=2 if mode == ProcessMode.DAEMON else 1,
            created_at=_ago(days=random.randint(5, 30)),
            updated_at=_ago(hours=random.randint(0, 48)),
        ))
    return processes


# ── Handlers ──────────────────────────────────────────────

HANDLER_DEFS = [
    ("triage-issues", "github.issue.*"),
    ("code-reviewer", "github.pull_request.opened"),
    ("alert-monitor", "system.alert.*"),
    ("email-responder", "email.received"),
    ("data-sync", "schedule.daily"),
    ("content-writer", "task.content.*"),
    ("deploy-manager", "deploy.requested"),
    ("weekly-digest", "schedule.weekly"),
]


def make_handlers(processes: list[Process]) -> list[Handler]:
    proc_map = {p.name: p for p in processes}
    handlers = []
    for proc_name, pattern in HANDLER_DEFS:
        if proc_name in proc_map:
            handlers.append(Handler(
                id=uuid4(),
                process=proc_map[proc_name].id,
                event_pattern=pattern,
                enabled=True,
                created_at=_ago(days=20),
            ))
    return handlers


# ── Files ─────────────────────────────────────────────────

FILE_DEFS = [
    ("config/system", "System-wide configuration and defaults.", ["config/alerts"]),
    ("config/alerts", "Alert thresholds and escalation rules.", []),
    ("prompts/triage-issues", "Prompt template for issue triage process.", []),
    ("prompts/code-reviewer", "Prompt template for code review process.", []),
    ("prompts/email-responder", "Prompt template for email response drafting.", []),
    ("data/brand-voice", "Brand voice guidelines for content generation.", []),
    ("data/team-contacts", "Team contact information and escalation paths.", []),
    ("data/faq", "Frequently asked questions and standard answers.", []),
    ("logs/deploy-2026-03-08", "Deployment log from last release.", []),
]


def make_files() -> tuple[list[File], list[FileVersion]]:
    files = []
    versions = []
    for key, content, includes in FILE_DEFS:
        f = File(
            id=uuid4(),
            key=key,
            includes=includes,
            created_at=_ago(days=random.randint(5, 30)),
            updated_at=_ago(hours=random.randint(0, 72)),
        )
        files.append(f)
        n_versions = random.randint(1, 3)
        for v in range(1, n_versions + 1):
            versions.append(FileVersion(
                id=uuid4(),
                file_id=f.id,
                version=v,
                content=f"v{v}: {content}",
                source="cogent" if v > 1 else "polis",
                is_active=v == n_versions,
                read_only=v < n_versions,
                created_at=_ago(days=30 - v),
            ))
    return files, versions


# ── Events ────────────────────────────────────────────────

EVENT_TYPES = [
    "github.issue.opened", "github.issue.closed", "github.pull_request.opened",
    "github.pull_request.merged", "email.received", "email.sent",
    "system.alert.fired", "system.alert.resolved", "task.content.created",
    "task.content.completed", "schedule.daily", "schedule.weekly",
    "deploy.requested", "deploy.completed", "health.check",
]

EVENT_SOURCES = [
    "github-webhook", "email-gateway", "cron-scheduler",
    "system-monitor", "user-action", "api-gateway",
]


def make_events(n: int = 40) -> list[Event]:
    events = []
    for _ in range(n):
        etype = random.choice(EVENT_TYPES)
        events.append(Event(
            id=uuid4(),
            event_type=etype,
            source=random.choice(EVENT_SOURCES),
            payload=_event_payload(etype),
            created_at=_ago(hours=random.randint(0, 72)),
        ))
    events.sort(key=lambda e: e.created_at or datetime.min)
    return events


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
        return {"environment": random.choice(["staging", "production"]),
                "version": f"v1.{random.randint(0, 9)}.{random.randint(0, 20)}"}
    return {"detail": etype}


# ── Runs ──────────────────────────────────────────────────

def make_runs(processes: list[Process], events: list[Event]) -> list[Run]:
    runs = []
    for proc in processes:
        n_runs = random.randint(1, 5)
        for j in range(n_runs):
            started = _ago(hours=random.randint(0, 72))
            if proc.status == ProcessStatus.COMPLETED and j == n_runs - 1:
                status = RunStatus.COMPLETED
            elif proc.status == ProcessStatus.RUNNING and j == n_runs - 1:
                status = RunStatus.RUNNING
            else:
                status = random.choice([RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.COMPLETED])
            duration = random.randint(5000, 120000) if status != RunStatus.RUNNING else None
            completed = started + timedelta(milliseconds=duration) if duration else None
            event = random.choice(events) if events and random.random() > 0.3 else None
            runs.append(Run(
                id=uuid4(),
                process=proc.id,
                event=event.id if event else None,
                status=status,
                tokens_in=random.randint(500, 15000),
                tokens_out=random.randint(200, 8000),
                cost_usd=Decimal(str(round(random.uniform(0.01, 0.50), 4))),
                duration_ms=duration,
                error="Rate limit exceeded" if status == RunStatus.FAILED and random.random() > 0.5 else
                      "Timeout after 120s" if status == RunStatus.FAILED else None,
                model_version="claude-sonnet-4-20250514" if random.random() > 0.3 else "claude-haiku-4-5-20251001",
                created_at=started,
                completed_at=completed,
            ))
    return runs


# ── Assemble & Write ─────────────────────────────────────

def generate(data_dir: str | None = None) -> Path:
    import os
    if data_dir is None:
        data_dir = os.environ.get("COGENT_LOCAL_DATA", str(Path.home() / ".cogent" / "local"))

    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "cogos_data.json"

    capabilities = make_capabilities()
    processes = make_processes()
    handlers = make_handlers(processes)
    files, file_versions = make_files()
    events = make_events(40)
    runs = make_runs(processes, events)

    data = {
        "processes": [p.model_dump(mode="json") for p in processes],
        "capabilities": [c.model_dump(mode="json") for c in capabilities],
        "handlers": [h.model_dump(mode="json") for h in handlers],
        "files": [f.model_dump(mode="json") for f in files],
        "file_versions": [fv.model_dump(mode="json") for fv in file_versions],
        "events": [e.model_dump(mode="json") for e in events],
        "runs": [r.model_dump(mode="json") for r in runs],
    }

    out_file.write_text(json.dumps(data, indent=2, default=_json_serial))
    print(f"Wrote cogos mock data to {out_file}")
    print(f"  {len(processes)} processes, {len(capabilities)} capabilities")
    print(f"  {len(handlers)} handlers, {len(files)} files, {len(file_versions)} file versions")
    print(f"  {len(events)} events, {len(runs)} runs")
    return out_file


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    generate(target)
