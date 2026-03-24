"""CogOS built-in capabilities — registry of all capability definitions."""

from __future__ import annotations

BUILTIN_CAPABILITIES: list[dict] = [
    # ── File & Directory ─────────────────────────────────────────
    # file, dir, blob
    {
        "name": "file",
        "description": "Single-file access — read, write, and search for a specific key.",
        "handler": "cogos.capabilities.files.FilesCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "key": {"type": "string", "description": "Restrict to a single file key"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["read", "write", "search"]}},
                },
            },
            "read": {
                "input": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "File key"},
                        "offset": {"type": "integer", "description": "Start line (0-indexed, negative from end)"},
                        "limit": {"type": "integer", "description": "Number of lines to return"},
                    },
                    "required": ["key"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "key": {"type": "string"},
                        "version": {"type": "integer"}, "content": {"type": "string"},
                        "read_only": {"type": "boolean"}, "source": {"type": "string"},
                        "total_lines": {"type": "integer"},
                    },
                },
            },
            "edit": {
                "input": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "File key"},
                        "old": {"type": "string", "description": "Exact string to find"},
                        "new": {"type": "string", "description": "Replacement string"},
                        "replace_all": {"type": "boolean", "default": False},
                    },
                    "required": ["key", "old", "new"],
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
            "search": {
                "input": {
                    "type": "object",
                    "properties": {"prefix": {"type": "string", "description": "Key prefix to search"}},
                },
                "output": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    {
        "name": "fs_dir",
        "description": "Directory access — list files and get file handles for read/write/append.",
        "handler": "cogos.capabilities.file_cap.DirCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "prefix": {"type": "string", "description": "Key prefix to restrict access"},
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
            "get": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "File key (relative to prefix)"}},
                    "required": ["key"],
                },
                "output": {
                    "type": "string",
                    "description": "FileCapability with read(), write(content), append(content)",
                },
            },
            "grep": {
                "input": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern to search"},
                        "prefix": {"type": "string", "description": "Narrow search prefix"},
                        "limit": {"type": "integer", "default": 20},
                        "context": {"type": "integer", "default": 0, "description": "Lines before/after match"},
                    },
                    "required": ["pattern"],
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "matches": {"type": "array", "items": {
                                "type": "object",
                                "properties": {
                                    "line": {"type": "integer"},
                                    "text": {"type": "string"},
                                    "before": {"type": "array", "items": {"type": "string"}},
                                    "after": {"type": "array", "items": {"type": "string"}},
                                },
                            }},
                        },
                    },
                },
            },
            "glob": {
                "input": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern (* = segment, ** = any depth, ? = char)",
                        },
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["pattern"],
                },
                "output": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"key": {"type": "string"}}},
                },
            },
            "tree": {
                "input": {
                    "type": "object",
                    "properties": {
                        "prefix": {"type": "string", "description": "Subtree prefix"},
                        "depth": {"type": "integer", "default": 3},
                    },
                },
                "output": {"type": "string", "description": "Tree-formatted string"},
            },
        },
    },
    # ── Process Management ───────────────────────────────────────
    # procs, me, process_handle
    {
        "name": "procs",
        "description": "Process management — list, inspect, and spawn processes.",
        "handler": "cogos.capabilities.procs.ProcsCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["list", "get", "spawn", "detach"]}},
                },
            },
            "list": {
                "input": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": [
                                "waiting", "runnable", "running", "blocked",
                                "suspended", "completed", "disabled",
                            ],
                        },
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
                        "schema": {"type": "string", "description": "JSON schema for structured output"},
                        "priority": {"type": "number", "default": 0.0},
                        "runner": {"type": "string", "enum": ["lambda", "ecs"], "default": "lambda"},
                        "model": {"type": "string", "description": "Model override"},
                        "capabilities": {
                            "type": "object",
                            "description": (
                                "Dict mapping grant name to capability instance"
                                " (scoped or unscoped). Not inherited."
                            ),
                            "additionalProperties": {
                                "description": "Capability instance or null for unscoped lookup by name",
                            },
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
        "name": "history",
        "description": "Run history, file mutation tracking, and cross-process audit queries.",
        "handler": "cogos.capabilities.history.HistoryCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["query", "process"]},
                    },
                    "process_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict to these process IDs. Empty = all.",
                    },
                },
            },
            "process": {
                "input": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Process name"},
                        "id": {"type": "string", "description": "Process UUID"},
                    },
                },
                "output": {"type": "object", "description": "ProcessHistory handle or HistoryError"},
            },
            "query": {
                "input": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Filter by run status"},
                        "process_name": {"type": "string", "description": "Glob pattern on process name"},
                        "since": {"type": "string", "description": "ISO timestamp or duration"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "process_id": {"type": "string"},
                            "process_name": {"type": "string"},
                            "status": {"type": "string"},
                            "duration_ms": {"type": "integer"},
                            "tokens_in": {"type": "integer"},
                            "tokens_out": {"type": "integer"},
                            "cost_usd": {"type": "string"},
                            "error": {"type": "string"},
                            "result": {"type": "object"},
                            "model_version": {"type": "string"},
                            "created_at": {"type": "string"},
                            "completed_at": {"type": "string"},
                        },
                    },
                },
            },
            "failed": {
                "input": {
                    "type": "object",
                    "properties": {
                        "since": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                },
                "output": {"type": "array"},
            },
        },
    },
    {
        "name": "resources",
        "description": "Resource pool management — check availability before resource-gated operations.",
        "handler": "cogos.capabilities.resources.ResourcesCapability",
        "instructions": "",
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
        "description": "Retrieve secrets from the runtime's secret store.",
        "handler": "cogos.capabilities.secrets.SecretsCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key patterns allowed (fnmatch)",
                    },
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
        "instructions": "",
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
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "channels": {"type": "array", "items": {"type": "string"}, "description": "Allowed channel IDs"},
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "send", "react", "create_thread", "dm",
                                "receive", "list_channels", "list_guilds",
                            ],
                        },
                    },
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
            "list_guilds": {
                "input": {"type": "object", "properties": {}},
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "guild_id": {"type": "string"}, "name": {"type": "string"},
                            "icon_url": {"type": "string"}, "member_count": {"type": "integer"},
                        },
                    },
                },
            },
            "list_channels": {
                "input": {
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string", "description": "Filter by guild ID"},
                    },
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "channel_id": {"type": "string"}, "guild_id": {"type": "string"},
                            "name": {"type": "string"}, "topic": {"type": "string"},
                            "category": {"type": "string"}, "channel_type": {"type": "string"},
                            "position": {"type": "integer"},
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
        "instructions": "",
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
        "description": "Process scheduling — message matching, process selection, and dispatch.",
        "handler": "cogos.capabilities.scheduler.SchedulerCapability",
        "instructions": "",
        "schema": {
            "match_messages": {
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
                    "properties": {
                        "slots": {
                            "type": "integer",
                            "default": 1,
                            "description": "Number of processes to select",
                        },
                    },
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
    # ── Channels & Scheduling ───────────────────────────────────
    # channels, scheduler, schemas
    {
        "name": "channels",
        "description": "Named topic channels for inter-process communication.",
        "handler": "cogos.capabilities.channels.ChannelsCapability",
        "instructions": "",
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
        "instructions": "",
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
    # ── Web Search & Fetch ──────────────────────────────────────
    # web_search, web_fetch
    {
        "name": "web_search",
        "description": (
            "Multi-backend web search: Tavily (general web),"
            " GitHub (repos/issues/code), Twitter/X (tweets)."
        ),
        "handler": "cogos.capabilities.web_search.WebSearchCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["search", "search_github", "search_twitter"]},
                    },
                },
            },
        },
    },
    {
        "name": "web_fetch",
        "description": "Fetch and extract content from URLs.",
        "handler": "cogos.capabilities.web_fetch.WebFetchCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "domains": {"type": "array", "items": {"type": "string"}, "description": "Domain allowlist"},
                },
            },
            "fetch": {
                "input": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                    },
                    "required": ["url"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"}, "html": {"type": "string"},
                        "status_code": {"type": "integer"},
                    },
                },
            },
            "extract_text": {
                "input": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to extract text from"},
                    },
                    "required": ["url"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"}, "text": {"type": "string"},
                        "title": {"type": "string"},
                    },
                },
            },
        },
    },
    # ── IO Integrations ─────────────────────────────────────────
    # asana, github, discord, email
    {
        "name": "asana",
        "description": "Create and manage Asana tasks.",
        "handler": "cogos.capabilities.asana_cap.AsanaCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "projects": {"type": "array", "items": {"type": "string"}, "description": "Allowed project GIDs"},
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "create_task", "update_task", "list_tasks",
                                "my_tasks", "add_comment",
                            ],
                        },
                    },
                },
            },
            "create_task": {
                "input": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"}, "name": {"type": "string"},
                        "notes": {"type": "string", "default": ""},
                        "assignee": {"type": "string"}, "due_on": {"type": "string"},
                    },
                    "required": ["project", "name"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "project": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
            "update_task": {
                "input": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "url": {"type": "string"}},
                },
            },
            "list_tasks": {
                "input": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"}, "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["project"],
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "assignee": {"type": "string"},
                            "due_on": {"type": "string"},
                            "completed": {"type": "boolean"},
                        },
                    },
                },
            },
            "my_tasks": {
                "input": {
                    "type": "object",
                    "properties": {
                        "workspace": {"type": "string", "description": "Workspace GID (auto-detected if omitted)"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "assignee": {"type": "string"},
                            "due_on": {"type": "string"},
                            "completed": {"type": "boolean"},
                        },
                    },
                },
            },
            "add_comment": {
                "input": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["task_id", "text"],
                },
                "output": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "task_id": {"type": "string"}},
                },
            },
        },
    },
    {
        "name": "github",
        "description": "Read GitHub user profiles, repositories, and contributions.",
        "handler": "cogos.capabilities.github_cap.GitHubCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "orgs": {"type": "array", "items": {"type": "string"}, "description": "Allowed organizations"},
                    "query_budget": {"type": "integer", "description": "Max API queries allowed"},
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "search_repos", "get_user",
                                "list_contributions", "get_repo",
                            ],
                        },
                    },
                },
            },
            "search_repos": {
                "input": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}, "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "full_name": {"type": "string"},
                            "description": {"type": "string"},
                            "stars": {"type": "integer"},
                            "language": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
            "get_user": {
                "input": {
                    "type": "object",
                    "properties": {"username": {"type": "string"}},
                    "required": ["username"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "login": {"type": "string"},
                        "name": {"type": "string"},
                        "bio": {"type": "string"},
                        "company": {"type": "string"},
                        "location": {"type": "string"},
                        "public_repos": {"type": "integer"},
                        "followers": {"type": "integer"},
                        "url": {"type": "string"},
                    },
                },
            },
            "list_contributions": {
                "input": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"}, "limit": {"type": "integer", "default": 30},
                    },
                    "required": ["username"],
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "repo": {"type": "string"},
                            "type": {"type": "string"},
                            "title": {"type": "string"},
                            "date": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
            },
            "get_repo": {
                "input": {
                    "type": "object",
                    "properties": {"owner": {"type": "string"}, "name": {"type": "string"}},
                    "required": ["owner", "name"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "full_name": {"type": "string"},
                        "description": {"type": "string"},
                        "stars": {"type": "integer"},
                        "forks": {"type": "integer"},
                        "language": {"type": "string"},
                        "topics": {"type": "array"},
                        "readme_excerpt": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
        },
    },
    # ── Google ──────────────────────────────────────────────
    {
        "name": "google.drive",
        "description": "Search, read, upload, and share Google Drive files.",
        "handler": "cogos.io.google.drive.DriveCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["search", "list", "get", "download", "upload", "share"],
                        },
                    },
                },
            },
            "search": {
                "input": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Drive query string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["query"],
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"}, "name": {"type": "string"},
                            "mime_type": {"type": "string"}, "size": {"type": "integer"},
                            "modified_time": {"type": "string"}, "web_view_link": {"type": "string"},
                        },
                    },
                },
            },
            "list": {
                "input": {
                    "type": "object",
                    "properties": {
                        "folder_id": {"type": "string", "description": "Folder ID (root if omitted)"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"}, "name": {"type": "string"},
                            "mime_type": {"type": "string"}, "size": {"type": "integer"},
                            "modified_time": {"type": "string"}, "web_view_link": {"type": "string"},
                        },
                    },
                },
            },
            "get": {
                "input": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Drive file ID"},
                    },
                    "required": ["file_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "mime_type": {"type": "string"}, "size": {"type": "integer"},
                        "modified_time": {"type": "string"}, "web_view_link": {"type": "string"},
                    },
                },
            },
            "download": {
                "input": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Drive file ID"},
                    },
                    "required": ["file_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"}, "name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "upload": {
                "input": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "File name"},
                        "content": {"type": "string", "description": "File content"},
                        "folder_id": {"type": "string", "description": "Parent folder ID"},
                        "mime_type": {"type": "string", "default": "text/plain"},
                    },
                    "required": ["name", "content"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "web_view_link": {"type": "string"},
                    },
                },
            },
            "share": {
                "input": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Drive file ID"},
                        "email": {"type": "string", "description": "Email to share with"},
                        "role": {"type": "string", "default": "reader", "enum": ["reader", "writer", "commenter"]},
                    },
                    "required": ["file_id", "email"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"}, "email": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "google.docs",
        "description": "Create, read, and update Google Docs.",
        "handler": "cogos.io.google.docs.DocsCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["create", "read", "update"],
                        },
                    },
                },
            },
            "create": {
                "input": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Document title"},
                        "content": {"type": "string", "default": "", "description": "Initial text content"},
                    },
                    "required": ["title"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "title": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
            "read": {
                "input": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Google Doc document ID"},
                    },
                    "required": ["doc_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "title": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "update": {
                "input": {
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "Google Doc document ID"},
                        "content": {"type": "string", "description": "New text content"},
                    },
                    "required": ["doc_id", "content"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "title": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "google.sheets",
        "description": "Create, read, and write Google Sheets.",
        "handler": "cogos.io.google.sheets.SheetsCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["create", "read", "write"],
                        },
                    },
                },
            },
            "create": {
                "input": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Spreadsheet title"},
                    },
                    "required": ["title"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "title": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
            "read": {
                "input": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                        "range": {"type": "string", "default": "Sheet1", "description": "A1 notation range"},
                    },
                    "required": ["spreadsheet_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string"}, "range": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                    },
                },
            },
            "write": {
                "input": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                        "range": {"type": "string", "description": "A1 notation range"},
                        "values": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "string"}},
                            "description": "2D array of cell values",
                        },
                    },
                    "required": ["spreadsheet_id", "range", "values"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {"type": "string"}, "updated_range": {"type": "string"},
                        "updated_rows": {"type": "integer"}, "updated_columns": {"type": "integer"},
                    },
                },
            },
        },
    },
    {
        "name": "google.calendar",
        "description": "Manage Google Calendar events.",
        "handler": "cogos.io.google.calendar.CalendarCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["list_events", "create_event", "update_event", "delete_event"],
                        },
                    },
                },
            },
            "list_events": {
                "input": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "ISO 8601 start datetime"},
                        "end": {"type": "string", "description": "ISO 8601 end datetime"},
                        "calendar_id": {"type": "string", "default": "primary"},
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["start", "end"],
                },
                "output": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"}, "title": {"type": "string"},
                            "start": {"type": "string"}, "end": {"type": "string"},
                            "description": {"type": "string"},
                            "attendees": {"type": "array", "items": {"type": "string"}},
                            "calendar_id": {"type": "string"}, "url": {"type": "string"},
                        },
                    },
                },
            },
            "create_event": {
                "input": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Event title"},
                        "start": {"type": "string", "description": "ISO 8601 start datetime"},
                        "end": {"type": "string", "description": "ISO 8601 end datetime"},
                        "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
                        "description": {"type": "string", "default": ""},
                        "calendar_id": {"type": "string", "default": "primary"},
                    },
                    "required": ["title", "start", "end"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "title": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
            "update_event": {
                "input": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Event ID to update"},
                        "calendar_id": {"type": "string", "default": "primary"},
                        "title": {"type": "string"}, "start": {"type": "string"},
                        "end": {"type": "string"}, "description": {"type": "string"},
                        "attendees": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["event_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "title": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
            "delete_event": {
                "input": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Event ID to delete"},
                        "calendar_id": {"type": "string", "default": "primary"},
                    },
                    "required": ["event_id"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"}, "deleted": {"type": "boolean"},
                    },
                },
            },
        },
    },
    # ── Cog Registry ───────────────────────────────────────────
    # cog_registry
    {
        "name": "cog_registry",
        "description": "Access to Cog objects for dynamic coglet creation.",
        "handler": "cogos.capabilities.cog_registry.CogRegistryCapability",
        "instructions": "",
        "schema": {
            "get_or_make_cog": {
                "input": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Cog directory path"},
                    },
                    "required": ["path"],
                },
                "output": {"type": "string", "description": "Cog object with make_coglet()"},
            },
        },
    },
    # ── Coglet Runtime ────────────────────────────────────────────
    # coglet_runtime
    {
        "name": "coglet_runtime",
        "description": "Run coglets as CogOS processes.",
        "handler": "cogos.capabilities.coglet_runtime.CogletRuntimeCapability",
        "instructions": "",
        "schema": {
            "run": {
                "input": {
                    "type": "object",
                    "properties": {
                        "coglet": {"type": "object", "description": "CogletManifest from cog.make_coglet()"},
                        "procs": {"type": "object", "description": "ProcsCapability instance"},
                        "capabilities": {"type": "object", "description": "Scoped capabilities to grant"},
                    },
                    "required": ["coglet", "procs"],
                },
                "output": {"type": "string", "description": "ProcessHandle for the spawned worker"},
            },
        },
    },
    # ── System ──────────────────────────────────────────────────
    # alerts, resources, secrets, schemas
    {
        "name": "alerts",
        "description": "Emit system alerts (warnings, errors) to the dashboard.",
        "handler": "cogos.capabilities.alerts.AlertsCapability",
        "instructions": "",
        "schema": {},
    },
    {
        "name": "blob",
        "description": "Upload and download files via S3 for cross-capability sharing.",
        "handler": "cogos.capabilities.blob.BlobCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["upload", "download"]}},
                    "max_size_bytes": {"type": "integer", "description": "Maximum upload size in bytes"},
                },
            },
            "upload": {
                "input": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string", "description": "Raw bytes to upload"},
                        "filename": {"type": "string", "description": "Filename for the blob"},
                        "content_type": {"type": "string", "description": "MIME type"},
                    },
                    "required": ["data", "filename"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"}, "url": {"type": "string"},
                        "filename": {"type": "string"}, "size": {"type": "integer"},
                    },
                },
            },
            "download": {
                "input": {
                    "type": "object",
                    "properties": {"key": {"type": "string", "description": "Blob key from upload"}},
                    "required": ["key"],
                },
                "output": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string"}, "filename": {"type": "string"},
                        "content_type": {"type": "string"},
                    },
                },
            },
        },
    },
    # ── Image ───────────────────────────────────────────────────
    # image
    {
        "name": "image",
        "description": "Manipulate, compose, analyze, and generate images. All operations are blob-key oriented.",
        "handler": "cogos.capabilities.image.ImageCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "resize", "crop", "rotate", "convert", "thumbnail",
                                "overlay_text", "watermark", "combine",
                                "describe", "analyze", "extract_text",
                                "generate", "edit", "variations",
                            ],
                        },
                    },
                },
            },
        },
    },
    # ── Web ─────────────────────────────────────────────────────
    # web, web_search, web_fetch
    {
        "name": "web",
        "description": "Publish web content and handle HTTP requests for the cogent's subdomain.",
        "handler": "cogos.io.web.capability.WebCapability",
        "instructions": "",
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["publish", "unpublish", "respond", "list", "url"],
                        },
                    },
                    "path_prefix": {"type": "string", "description": "Restrict to files under this prefix"},
                },
            },
        },
    },
    # ── Identity ──────────────────────────────────────────────────
    {
        "name": "cogent",
        "description": "Cogent identity — name and profile metadata.",
        "handler": "cogos.capabilities.cogent.CogentCapability",
        "instructions": "",
    },
    {
        "name": "monitor",
        "description": "Alert monitoring — run detection rules and dispatch actions.",
        "handler": "cogos.capabilities.alert_monitor.AlertMonitorCapability",
        "instructions": "",
        "schema": {},
    },
]
