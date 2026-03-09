"""CogOS built-in capabilities — handler registry."""

from __future__ import annotations

BUILTIN_CAPABILITIES: list[dict] = [
    {
        "name": "files",
        "description": "Versioned file store. files.read(key), files.write(key, content), files.search(prefix).",
        "handler": "cogos.capabilities.files.FilesCapability",
    },
    {
        "name": "procs",
        "description": "Process management. procs.list(), procs.get(name), procs.spawn(name, content).",
        "handler": "cogos.capabilities.procs.ProcsCapability",
    },
    {
        "name": "events",
        "description": "Append-only event log. events.emit(event_type, payload), events.query(event_type).",
        "handler": "cogos.capabilities.events.EventsCapability",
    },
    {
        "name": "resources",
        "description": "Resource pool management. resources.check().",
        "handler": "cogos.capabilities.resources.ResourcesCapability",
    },
    {
        "name": "secrets",
        "description": "Secret retrieval. secrets.get(key).",
        "handler": "cogos.capabilities.secrets.SecretsCapability",
    },
    {
        "name": "email",
        "description": "Send and receive emails. email.send(to, subject, body), email.receive(limit).",
        "handler": "cogos.io.email.capability.EmailCapability",
    },
    {
        "name": "scheduler",
        "description": "Process scheduling. scheduler.match_events(), scheduler.select_processes(), scheduler.dispatch_process(), scheduler.kill_process().",
        "handler": "cogos.capabilities.scheduler.SchedulerCapability",
    },
]
