"""CogOS built-in capabilities — handler registry."""

from __future__ import annotations

BUILTIN_CAPABILITIES: list[dict] = [
    {
        "name": "file",
        "description": "Single-file access — read, write, delete, and get metadata for a specific key.",
        "handler": "cogos.capabilities.files.FilesCapability",
        "instructions": (
            "Use file to access a single file by key.\n"
            "- file.read(key) — read a file by key\n"
            "- file.write(key, content) — create or update a file\n"
            "- file.delete(key) — delete a file\n"
            "- file.get_metadata(key) — get file metadata (versions, timestamps)\n"
            "Files are versioned. Every write creates a new version."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "key": {"type": "string", "description": "Restrict to a single file key"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["read", "write", "delete", "get_metadata"]}},
                },
            },
            "read": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "File key"}},
                    "required": ["key"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "key": {"type": "string"},
                        "version": {"type": "integer"}, "content": {"type": "string"},
                        "read_only": {"type": "boolean"}, "source": {"type": "string"},
                    },
                },
            },
            "write": {
                "input": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "File key"},
                        "content": {"type": "string", "description": "File content"},
                        "source": {"type": "string", "default": "agent"},
                        "read_only": {"type": "boolean", "default": False},
                        "includes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["key", "content"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "key": {"type": "string"},
                        "version": {"type": "integer"}, "created": {"type": "boolean"},
                        "changed": {"type": "boolean"},
                    },
                },
            },
            "delete": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "File key to delete"}},
                    "required": ["key"],
                },
                "output": {"type": "object", "properties": {"deleted": {"type": "boolean"}}},
            },
            "get_metadata": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "File key"}},
                    "required": ["key"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"}, "versions": {"type": "integer"},
                        "created_at": {"type": "string"}, "updated_at": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "dir",
        "description": "Directory access — list, read, write, create, and delete files under a prefix.",
        "handler": "cogos.capabilities.files.FilesCapability",
        "instructions": (
            "Use dir to access files under a directory prefix.\n"
            "- dir.list(prefix?) — list files under the prefix\n"
            "- dir.read(key) — read a file by key\n"
            "- dir.write(key, content) — create or update a file\n"
            "- dir.create(key, content) — create a new file (fails if exists)\n"
            "- dir.delete(key) — delete a file\n"
            "Dir grants full file access to everything under its prefix."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "prefix": {"type": "string", "description": "Key prefix to restrict access"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["list", "read", "write", "create", "delete"]}},
                },
            },
            "list": {
                "input": {
                    "type": "object",
                    "properties": {
                        "prefix": {"type": "string", "description": "Key prefix to filter by"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
                "output": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}, "key": {"type": "string"}}},
                },
            },
            "read": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "File key"}},
                    "required": ["key"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "key": {"type": "string"},
                        "version": {"type": "integer"}, "content": {"type": "string"},
                    },
                },
            },
            "write": {
                "input": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"}, "content": {"type": "string"},
                        "source": {"type": "string", "default": "agent"},
                    },
                    "required": ["key", "content"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "key": {"type": "string"},
                        "version": {"type": "integer"},
                    },
                },
            },
            "create": {
                "input": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"}, "content": {"type": "string"},
                        "source": {"type": "string", "default": "agent"},
                    },
                    "required": ["key", "content"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "key": {"type": "string"},
                        "version": {"type": "integer"},
                    },
                },
            },
            "delete": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
                "output": {"type": "object", "properties": {"deleted": {"type": "boolean"}}},
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
            "- procs.spawn(name, content, capabilities?) — create a new child process\n"
            "Spawned processes start in 'runnable' status. You must explicitly pass\n"
            "capability names via the capabilities parameter — they are NOT inherited."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["list", "get", "spawn"]}},
                },
            },
            "list": {
                "input": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["waiting", "runnable", "running", "blocked", "suspended", "completed", "disabled"]},
                        "limit": {"type": "integer", "default": 200},
                    },
                },
                "output": {
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
            },
            "get": {
                "input": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Process name"},
                        "id": {"type": "string", "description": "Process UUID"},
                    },
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "mode": {"type": "string"}, "status": {"type": "string"},
                        "content": {"type": "string"}, "priority": {"type": "number"},
                    },
                },
            },
            "spawn": {
                "input": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name for the new process"},
                        "content": {"type": "string", "default": "", "description": "Prompt/instructions"},
                        "code": {"type": "string", "description": "File UUID for prompt template"},
                        "priority": {"type": "number", "default": 0.0},
                        "runner": {"type": "string", "enum": ["lambda", "ecs"], "default": "lambda"},
                        "model": {"type": "string", "description": "Model override"},
                        "capabilities": {
                            "type": "object",
                            "description": "Dict mapping grant name to capability instance (scoped or unscoped). Not inherited.",
                            "additionalProperties": {"description": "Capability instance or null for unscoped lookup by name"},
                        },
                    },
                    "required": ["name"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "status": {"type": "string"}, "parent_process": {"type": "string"},
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
        "schema": {
            "check": {
                "input": {"type": "object", "properties": {}},
                "output": {
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
        "schema": {
            "scope": {
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "Key patterns allowed (fnmatch)"},
                },
            },
            "get": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "Secret name/parameter name"}},
                    "required": ["key"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"description": "Secret value (string or parsed JSON)"},
                    },
                },
            },
        },
    },
    {
        "name": "email",
        "description": "Send and receive emails via AWS SES.",
        "handler": "cogos.io.email.capability.EmailCapability",
        "event_types": ["email:received", "email:sent"],
        "instructions": (
            "Use email to send and receive emails.\n"
            "- email.send(to, subject, body, reply_to?) — send an email\n"
            "- email.receive(limit?) — read recent received emails from the event log\n"
            "Received emails arrive as 'email:received' events. Use receive() to read them.\n"
            "Always include a clear subject. Be professional in tone."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "to": {"type": "array", "items": {"type": "string"}, "description": "Allowed recipient addresses"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["send", "receive"]}},
                },
            },
            "send": {
                "input": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject line"},
                        "body": {"type": "string", "description": "Email body (plain text)"},
                        "reply_to": {"type": "string", "description": "Message-ID to reply to"},
                    },
                    "required": ["to", "subject", "body"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string"}, "to": {"type": "string"},
                        "subject": {"type": "string"},
                    },
                },
            },
            "receive": {
                "input": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10, "description": "Max emails to return"},
                    },
                },
                "output": {
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
    },
    {
        "name": "discord",
        "description": "Send and receive Discord messages, reactions, threads, and DMs.",
        "handler": "cogos.io.discord.capability.DiscordCapability",
        "event_types": ["discord:dm", "discord:mention", "discord:message"],
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
        "schema": {
            "scope": {
                "properties": {
                    "channels": {"type": "array", "items": {"type": "string"}, "description": "Allowed channel IDs"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["send", "react", "create_thread", "dm", "receive"]}},
                },
            },
            "send": {
                "input": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel ID"},
                        "content": {"type": "string", "description": "Message content"},
                        "thread_id": {"type": "string", "description": "Thread ID to reply in"},
                        "reply_to": {"type": "string", "description": "Message ID to reply to"},
                    },
                    "required": ["channel", "content"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string"}, "content_length": {"type": "integer"},
                        "type": {"type": "string"},
                    },
                },
            },
            "react": {
                "input": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string"}, "message_id": {"type": "string"},
                        "emoji": {"type": "string", "description": "Emoji name or unicode"},
                    },
                    "required": ["channel", "message_id", "emoji"],
                },
                "output": {"type": "object", "properties": {}},
            },
            "create_thread": {
                "input": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string"}, "thread_name": {"type": "string"},
                        "content": {"type": "string", "default": ""},
                        "message_id": {"type": "string", "description": "Message to create thread from"},
                    },
                    "required": ["channel", "thread_name"],
                },
                "output": {"type": "object", "properties": {}},
            },
            "dm": {
                "input": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"}, "content": {"type": "string"},
                    },
                    "required": ["user_id", "content"],
                },
                "output": {"type": "object", "properties": {}},
            },
            "receive": {
                "input": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                        "event_type": {"type": "string", "enum": ["discord:dm", "discord:mention", "discord:message"]},
                    },
                },
                "output": {
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
        "schema": {
            "run": {
                "input": {"type": "object", "properties": {}},
                "output": {
                    "type": "object",
                    "description": "RunScope with .tmp(), .tmp_dir(), .log(), .scratch(), .scratch_dir()",
                },
            },
            "process": {
                "input": {"type": "object", "properties": {}},
                "output": {
                    "type": "object",
                    "description": "ProcessScope with .tmp(), .tmp_dir(), .log(), .scratch(), .scratch_dir()",
                },
            },
        },
    },
    {
        "name": "scheduler",
        "description": "Process scheduling — event matching, process selection, and dispatch.",
        "handler": "cogos.capabilities.scheduler.SchedulerCapability",
        "event_types": ["process:run:success", "process:run:failed", "process:status:runnable"],
        "instructions": (
            "The scheduler runs the CogOS tick loop. Only the scheduler daemon should use this.\n"
            "- scheduler.match_events() — match undelivered events to handlers, create deliveries\n"
            "- scheduler.unblock_processes() — move BLOCKED processes to RUNNABLE if resources free\n"
            "- scheduler.select_processes(slots) — pick RUNNABLE processes by priority (softmax sampling)\n"
            "- scheduler.dispatch_process(process_id) — transition to RUNNING, create a Run record\n"
            "- scheduler.kill_process(process_id) — disable a process, fail its running run\n"
            "Always run in order: match_events -> unblock_processes -> select_processes -> dispatch."
        ),
        "schema": {
            "match_events": {
                "input": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 200}},
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "deliveries_created": {"type": "integer"},
                        "deliveries": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "unblock_processes": {
                "input": {"type": "object", "properties": {}},
                "output": {
                    "type": "object",
                    "properties": {
                        "unblocked_count": {"type": "integer"},
                        "unblocked": {"type": "array", "items": {"type": "object"}},
                    },
                },
            },
            "select_processes": {
                "input": {
                    "type": "object",
                    "properties": {"slots": {"type": "integer", "default": 1, "description": "Number of processes to select"}},
                },
                "output": {
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
            },
            "dispatch_process": {
                "input": {
                    "type": "object",
                    "properties": {"process_id": {"type": "string", "description": "UUID of the process to dispatch"}},
                    "required": ["process_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string"}, "process_id": {"type": "string"},
                        "process_name": {"type": "string"}, "runner": {"type": "string"},
                    },
                },
            },
            "kill_process": {
                "input": {
                    "type": "object",
                    "properties": {"process_id": {"type": "string", "description": "UUID of the process to kill"}},
                    "required": ["process_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "process_id": {"type": "string"}, "name": {"type": "string"},
                        "previous_status": {"type": "string"}, "new_status": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "channels",
        "description": "Named topic channels for inter-process communication.",
        "handler": "cogos.capabilities.channels.ChannelsCapability",
        "instructions": (
            "Use channels to create and interact with typed message channels.\n"
            "- channels.create(name, schema) — create a named channel with schema\n"
            "- channels.send(name, payload) — send a message to a channel\n"
            "- channels.read(name, limit?) — read messages from a channel\n"
            "- channels.subscribe(name) — subscribe for push notifications\n"
            "- channels.list() — list available channels\n"
            "- channels.get(name) — get channel details\n"
            "- channels.close(name) — close a channel you own\n"
            "- channels.schema(name) — get channel schema\n"
            "Messages are validated against the channel's schema on send."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["create", "list", "get", "send", "read", "subscribe", "close"],
                        },
                    },
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Channel name patterns (fnmatch)",
                    },
                },
            },
        },
    },
    {
        "name": "schemas",
        "description": "Schema definitions for channel messages.",
        "handler": "cogos.capabilities.schemas.SchemasCapability",
        "instructions": (
            "Use schemas to discover message type definitions.\n"
            "- schemas.get(name) — get a schema by name\n"
            "- schemas.list() — list all available schemas\n"
            "Schemas define the structure of channel messages."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Schema name patterns (fnmatch)",
                    },
                },
            },
        },
    },
]
