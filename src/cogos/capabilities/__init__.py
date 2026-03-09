"""CogOS built-in capabilities — handler registry."""

from __future__ import annotations

BUILTIN_CAPABILITIES: list[dict] = [
    # ── Files ────────────────────────────────────────────────
    {
        "name": "files/read",
        "description": "Read a file's active content by key.",
        "handler": "cogos.capabilities.files.read",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Hierarchical file key."},
            },
            "required": ["key"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "key": {"type": "string"},
                "version": {"type": "integer"},
                "content": {"type": "string"},
                "read_only": {"type": "boolean"},
                "source": {"type": "string"},
            },
        },
    },
    {
        "name": "files/write",
        "description": "Write content to a file, creating or versioning it.",
        "handler": "cogos.capabilities.files.write",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Hierarchical file key."},
                "content": {"type": "string", "description": "File content."},
                "source": {"type": "string", "description": "Who is writing.", "default": "agent"},
                "read_only": {"type": "boolean", "default": False},
                "includes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File keys to include (for prompt templates).",
                },
            },
            "required": ["key", "content"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "key": {"type": "string"},
                "version": {"type": "integer"},
                "created": {"type": "boolean"},
            },
        },
    },
    {
        "name": "files/search",
        "description": "Search for files by key prefix.",
        "handler": "cogos.capabilities.files.search",
        "input_schema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Key prefix to filter by."},
                "limit": {"type": "integer", "default": 50},
            },
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "key": {"type": "string"},
                },
            },
        },
    },
    # ── Processes ────────────────────────────────────────────
    {
        "name": "procs/list",
        "description": "List processes, optionally filtering by status.",
        "handler": "cogos.capabilities.procs.list_procs",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["waiting", "runnable", "running", "blocked",
                             "suspended", "completed", "disabled"],
                },
                "limit": {"type": "integer", "default": 200},
            },
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "mode": {"type": "string"},
                    "status": {"type": "string"},
                    "priority": {"type": "number"},
                    "runner": {"type": "string"},
                },
            },
        },
    },
    {
        "name": "procs/get",
        "description": "Get details of a process by name or ID.",
        "handler": "cogos.capabilities.procs.get_proc",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "id": {"type": "string", "format": "uuid"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "name": {"type": "string"},
                "mode": {"type": "string"},
                "status": {"type": "string"},
                "priority": {"type": "number"},
                "runner": {"type": "string"},
                "content": {"type": "string"},
                "code": {"type": "string", "format": "uuid"},
                "preemptible": {"type": "boolean"},
                "model": {"type": "string"},
            },
        },
    },
    {
        "name": "procs/spawn",
        "description": "Spawn a child one_shot process under the calling process.",
        "handler": "cogos.capabilities.procs.spawn",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique process name."},
                "content": {"type": "string", "description": "Process-specific payload."},
                "code": {"type": "string", "format": "uuid", "description": "File ID for prompt template."},
                "priority": {"type": "number", "default": 0.0},
                "runner": {"type": "string", "enum": ["lambda", "ecs"], "default": "lambda"},
                "model": {"type": "string", "description": "Preferred LLM model."},
            },
            "required": ["name"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "name": {"type": "string"},
                "status": {"type": "string"},
                "parent_process": {"type": "string", "format": "uuid"},
            },
        },
    },
    # ── Events ───────────────────────────────────────────────
    {
        "name": "events/emit",
        "description": "Emit a new event into the append-only log.",
        "handler": "cogos.capabilities.events.emit",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "Hierarchical event type."},
                "payload": {"type": "object", "description": "Event payload."},
                "parent_event": {"type": "string", "format": "uuid", "description": "Causal parent."},
            },
            "required": ["event_type"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "event_type": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
            },
        },
    },
    {
        "name": "events/query",
        "description": "Query events, optionally filtering by type.",
        "handler": "cogos.capabilities.events.query",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "event_type": {"type": "string"},
                    "source": {"type": "string"},
                    "payload": {"type": "object"},
                    "created_at": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
    # ── Resources ────────────────────────────────────────────
    {
        "name": "resources/check",
        "description": "Check resource availability for the calling process.",
        "handler": "cogos.capabilities.resources.check",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "resources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "name": {"type": "string"},
                            "capacity": {"type": "number"},
                            "used": {"type": "number"},
                            "remaining": {"type": "number"},
                            "available": {"type": "boolean"},
                        },
                    },
                },
                "available": {"type": "boolean"},
            },
        },
    },
    # ── Secrets ──────────────────────────────────────────────
    {
        "name": "secrets/get",
        "description": "Retrieve a secret from the key manager by key.",
        "handler": "cogos.capabilities.secrets.get",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Secret key (e.g. SSM path or Secrets Manager ARN)."},
            },
            "required": ["key"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {},
                "error": {"type": "string"},
            },
        },
    },
    # ── Scheduler ────────────────────────────────────────────
    {
        "name": "scheduler/match_events",
        "description": "Find undelivered events, match to handlers, create EventDelivery rows.",
        "handler": "cogos.capabilities.scheduler.match_events",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200, "description": "Max events to scan."},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "deliveries_created": {"type": "integer"},
                "deliveries": {"type": "array"},
            },
        },
    },
    {
        "name": "scheduler/select_processes",
        "description": "Softmax sample from RUNNABLE processes by effective priority.",
        "handler": "cogos.capabilities.scheduler.select_processes",
        "input_schema": {
            "type": "object",
            "properties": {
                "slots": {"type": "integer", "default": 1, "description": "Number of execution slots."},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "selected": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "name": {"type": "string"},
                            "priority": {"type": "number"},
                            "effective_priority": {"type": "number"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "scheduler/dispatch_process",
        "description": "Transition a process to RUNNING and create a Run record.",
        "handler": "cogos.capabilities.scheduler.dispatch_process",
        "input_schema": {
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "format": "uuid"},
            },
            "required": ["process_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "format": "uuid"},
                "process_id": {"type": "string", "format": "uuid"},
                "process_name": {"type": "string"},
                "runner": {"type": "string"},
                "event_id": {"type": "string", "format": "uuid"},
            },
        },
    },
    {
        "name": "scheduler/unblock_processes",
        "description": "Move BLOCKED processes to RUNNABLE when resources become available.",
        "handler": "cogos.capabilities.scheduler.unblock_processes",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "unblocked_count": {"type": "integer"},
                "unblocked": {"type": "array"},
            },
        },
    },
    {
        "name": "scheduler/kill_process",
        "description": "Force-terminate a process by setting it to DISABLED.",
        "handler": "cogos.capabilities.scheduler.kill_process",
        "input_schema": {
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "format": "uuid"},
            },
            "required": ["process_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "format": "uuid"},
                "name": {"type": "string"},
                "previous_status": {"type": "string"},
                "new_status": {"type": "string"},
            },
        },
    },
]
