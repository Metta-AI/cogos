"""CogOS built-in capabilities — handler registry."""

from __future__ import annotations

BUILTIN_CAPABILITIES: list[dict] = [
    {
        "name": "files",
        "description": "Versioned file store for persistent documents, configs, and prompts.",
        "handler": "cogos.capabilities.files.FilesCapability",
        "instructions": (
            "Use files to read and write persistent documents.\n"
            "- files.read(key) — read a file by key (e.g. 'config/system')\n"
            "- files.write(key, content) — create or update a file\n"
            "- files.search(prefix) — list files matching a prefix\n"
            "Files are versioned. Every write creates a new version."
        ),
        "input_schema": {
            "read": {
                "type": "object",
                "properties": {"key": {"type": "string", "description": "File key (path-like, e.g. 'config/system')"}},
                "required": ["key"],
            },
            "write": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "File key"},
                    "content": {"type": "string", "description": "File content"},
                    "source": {"type": "string", "default": "agent", "description": "Who wrote it"},
                    "read_only": {"type": "boolean", "default": False},
                    "includes": {"type": "array", "items": {"type": "string"}, "description": "Keys of files to include"},
                },
                "required": ["key", "content"],
            },
            "search": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Key prefix to filter by"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
        "output_schema": {
            "read": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "key": {"type": "string"},
                    "version": {"type": "integer"}, "content": {"type": "string"},
                    "read_only": {"type": "boolean"}, "source": {"type": "string"},
                },
            },
            "write": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "key": {"type": "string"},
                    "version": {"type": "integer"}, "created": {"type": "boolean"},
                    "changed": {"type": "boolean"},
                },
            },
            "search": {
                "type": "array",
                "items": {"type": "object", "properties": {"id": {"type": "string"}, "key": {"type": "string"}}},
            },
        },
    },
    {
        "name": "procs",
        "description": "Process management — list, inspect, and spawn processes.",
        "handler": "cogos.capabilities.procs.ProcsCapability",
        "instructions": (
            "Use procs to manage CogOS processes.\n"
            "- procs.list(status?) — list processes, optionally filtered by status\n"
            "- procs.get(name) — get full details of a process by name or id\n"
            "- procs.spawn(name, content) — create a new child process\n"
            "Spawned processes inherit the current process as parent and start in 'waiting' status."
        ),
        "input_schema": {
            "list": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["waiting", "runnable", "running", "blocked", "suspended", "completed", "disabled"]},
                    "limit": {"type": "integer", "default": 200},
                },
            },
            "get": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Process name"},
                    "id": {"type": "string", "description": "Process UUID"},
                },
            },
            "spawn": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the new process"},
                    "content": {"type": "string", "default": "", "description": "Prompt/instructions"},
                    "code": {"type": "string", "description": "File UUID for prompt template"},
                    "priority": {"type": "number", "default": 0.0},
                    "runner": {"type": "string", "enum": ["lambda", "ecs"], "default": "lambda"},
                    "model": {"type": "string", "description": "Model override"},
                },
                "required": ["name"],
            },
        },
        "output_schema": {
            "list": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "mode": {"type": "string"}, "status": {"type": "string"},
                        "priority": {"type": "number"}, "runner": {"type": "string"},
                    },
                },
            },
            "get": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "name": {"type": "string"},
                    "mode": {"type": "string"}, "status": {"type": "string"},
                    "content": {"type": "string"}, "priority": {"type": "number"},
                },
            },
            "spawn": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "name": {"type": "string"},
                    "status": {"type": "string"}, "parent_process": {"type": "string"},
                },
            },
        },
    },
    {
        "name": "events",
        "description": "Append-only event log for inter-process communication.",
        "handler": "cogos.capabilities.events.EventsCapability",
        "instructions": (
            "Use events to emit and query the event log.\n"
            "- events.emit(event_type, payload?) — emit an event (e.g. 'task:completed')\n"
            "- events.query(event_type?, limit?) — query recent events\n"
            "Events are immutable once emitted. Handlers can subscribe to event types."
        ),
        "input_schema": {
            "emit": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Event type (e.g. 'task:completed')"},
                    "payload": {"type": "object", "description": "Arbitrary JSON payload"},
                    "parent_event": {"type": "string", "description": "Parent event UUID for chaining"},
                },
                "required": ["event_type"],
            },
            "query": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Filter by event type"},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
        "output_schema": {
            "emit": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "event_type": {"type": "string"},
                    "created_at": {"type": "string"},
                },
            },
            "query": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "event_type": {"type": "string"},
                        "source": {"type": "string"}, "payload": {"type": "object"},
                        "created_at": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "resources",
        "description": "Resource pool management — check availability before resource-gated operations.",
        "handler": "cogos.capabilities.resources.ResourcesCapability",
        "instructions": (
            "Use resources to check whether your process's required resources are available.\n"
            "- resources.check() — returns availability of all resources assigned to the current process\n"
            "If resources are unavailable, your process may be blocked by the scheduler."
        ),
        "input_schema": {
            "check": {"type": "object", "properties": {}},
        },
        "output_schema": {
            "check": {
                "type": "object",
                "properties": {
                    "available": {"type": "boolean", "description": "True if all resources are available"},
                    "resources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"}, "name": {"type": "string"},
                                "capacity": {"type": "integer"}, "used": {"type": "integer"},
                                "remaining": {"type": "integer"}, "available": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        },
    },
    {
        "name": "secrets",
        "description": "Retrieve secrets from AWS SSM Parameter Store or Secrets Manager.",
        "handler": "cogos.capabilities.secrets.SecretsCapability",
        "instructions": (
            "Use secrets to retrieve API keys, tokens, and other sensitive values.\n"
            "- secrets.get(key) — retrieve a secret by name\n"
            "Tries SSM Parameter Store first, then falls back to Secrets Manager.\n"
            "JSON values are automatically parsed. Never log or emit secret values."
        ),
        "input_schema": {
            "get": {
                "type": "object",
                "properties": {"key": {"type": "string", "description": "Secret name/parameter name"}},
                "required": ["key"],
            },
        },
        "output_schema": {
            "get": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"description": "Secret value (string or parsed JSON)"},
                },
            },
        },
    },
    {
        "name": "email",
        "description": "Send and receive emails via AWS SES.",
        "handler": "cogos.io.email.capability.EmailCapability",
        "instructions": (
            "Use email to send and receive emails.\n"
            "- email.send(to, subject, body, reply_to?) — send an email\n"
            "- email.receive(limit?) — read recent received emails from the event log\n"
            "Received emails arrive as 'email:received' events. Use receive() to read them.\n"
            "Always include a clear subject. Be professional in tone."
        ),
        "input_schema": {
            "send": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "reply_to": {"type": "string", "description": "Message-ID to reply to"},
                },
                "required": ["to", "subject", "body"],
            },
            "receive": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10, "description": "Max emails to return"},
                },
            },
        },
        "output_schema": {
            "send": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"}, "to": {"type": "string"},
                    "subject": {"type": "string"},
                },
            },
            "receive": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"}, "to": {"type": "string"},
                        "subject": {"type": "string"}, "body": {"type": "string"},
                        "date": {"type": "string"}, "message_id": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "discord",
        "description": "Send and receive Discord messages, reactions, threads, and DMs.",
        "handler": "cogos.io.discord.capability.DiscordCapability",
        "instructions": (
            "Use discord to interact with Discord channels.\n"
            "- discord.send(channel, content) — send a message to a channel\n"
            "- discord.react(channel, message_id, emoji) — add a reaction\n"
            "- discord.create_thread(channel, thread_name, content?) — create a thread\n"
            "- discord.dm(user_id, content) — send a direct message\n"
            "- discord.receive(limit?, event_type?) — read recent Discord messages\n"
            "Event types: discord:dm, discord:mention, discord:message.\n"
            "Keep messages concise. Use threads for extended discussions."
        ),
        "input_schema": {
            "send": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel ID"},
                    "content": {"type": "string", "description": "Message content"},
                    "thread_id": {"type": "string", "description": "Thread ID to reply in"},
                    "reply_to": {"type": "string", "description": "Message ID to reply to"},
                },
                "required": ["channel", "content"],
            },
            "react": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"}, "message_id": {"type": "string"},
                    "emoji": {"type": "string", "description": "Emoji name or unicode"},
                },
                "required": ["channel", "message_id", "emoji"],
            },
            "create_thread": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"}, "thread_name": {"type": "string"},
                    "content": {"type": "string", "default": ""},
                    "message_id": {"type": "string", "description": "Message to create thread from"},
                },
                "required": ["channel", "thread_name"],
            },
            "dm": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"}, "content": {"type": "string"},
                },
                "required": ["user_id", "content"],
            },
            "receive": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "event_type": {"type": "string", "enum": ["discord:dm", "discord:mention", "discord:message"]},
                },
            },
        },
        "output_schema": {
            "send": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"}, "content_length": {"type": "integer"},
                    "type": {"type": "string"},
                },
            },
            "receive": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"}, "author": {"type": "string"},
                        "author_id": {"type": "string"}, "channel_id": {"type": "string"},
                        "message_id": {"type": "string"}, "is_dm": {"type": "boolean"},
                        "is_mention": {"type": "boolean"}, "event_type": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "me",
        "description": "Self-referential capability — scoped file/dir access for the current process and run.",
        "handler": "cogos.capabilities.me.MeCapability",
        "instructions": (
            "Use me to access scoped scratch/tmp/log storage for the current process and run.\n"
            "- me.run() — returns a RunScope with scratch/tmp/log scoped to the current run\n"
            "- me.process() — returns a ProcessScope with scratch/tmp/log scoped to the process\n"
            "\n"
            "Each scope provides:\n"
            "- .tmp() — a FileHandle for a single tmp file\n"
            "- .tmp_dir() — a DirHandle for tmp files (list/read/write by name)\n"
            "- .log() — a FileHandle for a log file\n"
            "- .scratch() — a FileHandle for a single scratch file\n"
            "- .scratch_dir() — a DirHandle for scratch files (list/read/write by name)\n"
            "\n"
            "FileHandle: .read() -> str, .write(content) -> result, .key -> str\n"
            "DirHandle: .list() -> [keys], .read(name) -> str, .write(name, content) -> result, .file(name) -> FileHandle\n"
            "\n"
            "Run-scoped storage is ephemeral per run. Process-scoped storage persists across runs.\n"
            "Paths: /proc/{process_id}/[tmp|scratch|log] and /proc/{process_id}/runs/{run_id}/[tmp|scratch|log]"
        ),
        "input_schema": {
            "run": {"type": "object", "properties": {}},
            "process": {"type": "object", "properties": {}},
        },
        "output_schema": {
            "run": {
                "type": "object",
                "description": "RunScope with .tmp(), .tmp_dir(), .log(), .scratch(), .scratch_dir()",
            },
            "process": {
                "type": "object",
                "description": "ProcessScope with .tmp(), .tmp_dir(), .log(), .scratch(), .scratch_dir()",
            },
        },
    },
    {
        "name": "scheduler",
        "description": "Process scheduling — event matching, process selection, and dispatch.",
        "handler": "cogos.capabilities.scheduler.SchedulerCapability",
        "instructions": (
            "The scheduler runs the CogOS tick loop. Only the scheduler daemon should use this.\n"
            "- scheduler.match_events() — match undelivered events to handlers, create deliveries\n"
            "- scheduler.unblock_processes() — move BLOCKED processes to RUNNABLE if resources free\n"
            "- scheduler.select_processes(slots) — pick RUNNABLE processes by priority (softmax sampling)\n"
            "- scheduler.dispatch_process(process_id) — transition to RUNNING, create a Run record\n"
            "- scheduler.kill_process(process_id) — disable a process, fail its running run\n"
            "Always run in order: match_events -> unblock_processes -> select_processes -> dispatch."
        ),
        "input_schema": {
            "match_events": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 200}},
            },
            "unblock_processes": {"type": "object", "properties": {}},
            "select_processes": {
                "type": "object",
                "properties": {"slots": {"type": "integer", "default": 1, "description": "Number of processes to select"}},
            },
            "dispatch_process": {
                "type": "object",
                "properties": {"process_id": {"type": "string", "description": "UUID of the process to dispatch"}},
                "required": ["process_id"],
            },
            "kill_process": {
                "type": "object",
                "properties": {"process_id": {"type": "string", "description": "UUID of the process to kill"}},
                "required": ["process_id"],
            },
        },
        "output_schema": {
            "match_events": {
                "type": "object",
                "properties": {
                    "deliveries_created": {"type": "integer"},
                    "deliveries": {"type": "array", "items": {"type": "object"}},
                },
            },
            "unblock_processes": {
                "type": "object",
                "properties": {
                    "unblocked_count": {"type": "integer"},
                    "unblocked": {"type": "array", "items": {"type": "object"}},
                },
            },
            "select_processes": {
                "type": "object",
                "properties": {
                    "selected": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"}, "name": {"type": "string"},
                                "priority": {"type": "number"}, "effective_priority": {"type": "number"},
                            },
                        },
                    },
                },
            },
            "dispatch_process": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"}, "process_id": {"type": "string"},
                    "process_name": {"type": "string"}, "runner": {"type": "string"},
                },
            },
            "kill_process": {
                "type": "object",
                "properties": {
                    "process_id": {"type": "string"}, "name": {"type": "string"},
                    "previous_status": {"type": "string"}, "new_status": {"type": "string"},
                },
            },
        },
    },
]
