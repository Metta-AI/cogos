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
        "description": "Directory access — list files and get file handles for read/write/append.",
        "handler": "cogos.capabilities.file_cap.DirCapability",
        "instructions": (
            "Use dir to access files under a directory prefix.\n"
            "- dir.list(prefix?) — list files\n"
            "- f = dir.get(key) — get a file handle\n"
            "- f.read() — read file content\n"
            "- f.write(content) — overwrite file\n"
            "- f.append(content) — append to file (creates if missing)\n"
            "Example: f = dir.get('log.txt'); f.append('\\nnew line'); print(f.read().content)"
        ),
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
                "output": {"type": "string", "description": "FileCapability with read(), write(content), append(content)"},
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
        "instructions": (
            "Use email to send and receive emails.\n"
            "- email.send(to, subject, body, reply_to?) — send an email\n"
            "- email.receive(limit?) — read recent received emails\n"
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
        "instructions": (
            "Use discord to interact with Discord channels.\n"
            "- discord.send(channel, content) — send a message to a channel\n"
            "- discord.react(channel, message_id, emoji) — add a reaction\n"
            "- discord.create_thread(channel, thread_name, content?) — create a thread\n"
            "- discord.dm(user_id, content) — send a direct message\n"
            "- discord.receive(limit?, channel?) — read recent Discord messages\n"
            "Keep messages concise. Use threads for extended discussions."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "channels": {"type": "array", "items": {"type": "string"}, "description": "Allowed channel IDs"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["send", "react", "create_thread", "dm", "receive", "list_channels", "list_guilds"]}},
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
        "description": "Process scheduling — message matching, process selection, and dispatch.",
        "handler": "cogos.capabilities.scheduler.SchedulerCapability",
        "instructions": (
            "The scheduler runs the CogOS tick loop. Only the scheduler daemon should use this.\n"
            "- scheduler.match_messages() — match undelivered channel messages to handlers, create deliveries\n"
            "- scheduler.unblock_processes() — move BLOCKED processes to RUNNABLE if resources free\n"
            "- scheduler.select_processes(slots) — pick RUNNABLE processes by priority (softmax sampling)\n"
            "- scheduler.dispatch_process(process_id) — transition to RUNNING, create a Run record\n"
            "- scheduler.kill_process(process_id) — disable a process, fail its running run\n"
            "Always run in order: match_messages -> unblock_processes -> select_processes -> dispatch."
        ),
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
    {
        "name": "web_search",
        "description": "Multi-backend web search: Perplexity (general web), GitHub (repos/issues/code), Twitter/X (tweets).",
        "handler": "cogos.capabilities.web_search.WebSearchCapability",
        "instructions": (
            "Use web_search to research topics across multiple sources.\n"
            "- web_search.search(query, recency?, after_date?, before_date?) — general web search via Perplexity; recency: 'day'|'week'|'month'\n"
            "- web_search.search_github(query, search_type?, after_date?, before_date?) — GitHub search; search_type: 'repositories'|'issues'|'discussions'|'code'\n"
            "- web_search.search_twitter(query, recency?, after_date?, before_date?) — Twitter/X tweet search via X API v2\n"
            "Use recency='day' for latest news. Use after_date/before_date (ISO date strings) for backfill."
        ),
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
        "instructions": (
            "Use web_fetch to fetch web pages and extract text.\n"
            "- web_fetch.fetch(url) — fetch raw HTML from a URL\n"
            "- web_fetch.extract_text(url) — fetch and extract clean text content\n"
            "Returns PageContent/TextContent or FetchError.\n"
            "Useful for reading GitHub profiles, blog posts, articles."
        ),
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
    {
        "name": "asana",
        "description": "Create and manage Asana tasks.",
        "handler": "cogos.capabilities.asana_cap.AsanaCapability",
        "instructions": (
            "Use asana to manage tasks in Asana.\n"
            "- asana.create_task(project, name, notes?, assignee?, due_on?) — create a task\n"
            "- asana.update_task(task_id, **fields) — update a task\n"
            "- asana.list_tasks(project, limit=50) — list tasks in a project\n"
            "- asana.add_comment(task_id, text) — add a comment to a task\n"
            "API key is managed internally. Uses Asana PAT for authentication."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "projects": {"type": "array", "items": {"type": "string"}, "description": "Allowed project GIDs"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["create_task", "update_task", "list_tasks", "add_comment"]}},
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
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "project": {"type": "string"}, "url": {"type": "string"}},
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
                        "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "assignee": {"type": "string"}, "due_on": {"type": "string"}, "completed": {"type": "boolean"}},
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
        "instructions": (
            "Use github to read GitHub data (read-only).\n"
            "- github.search_repos(query, limit=10) — search repositories\n"
            "- github.get_user(username) — get a user profile\n"
            "- github.list_contributions(username, limit=30) — list recent activity\n"
            "- github.get_repo(owner, name) — get repo details with readme excerpt\n"
            "API key is managed internally. All operations are read-only."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "orgs": {"type": "array", "items": {"type": "string"}, "description": "Allowed organizations"},
                    "query_budget": {"type": "integer", "description": "Max API queries allowed"},
                    "ops": {"type": "array", "items": {"type": "string", "enum": ["search_repos", "get_user", "list_contributions", "get_repo"]}},
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
                        "properties": {"full_name": {"type": "string"}, "description": {"type": "string"}, "stars": {"type": "integer"}, "language": {"type": "string"}, "url": {"type": "string"}},
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
                    "properties": {"login": {"type": "string"}, "name": {"type": "string"}, "bio": {"type": "string"}, "company": {"type": "string"}, "location": {"type": "string"}, "public_repos": {"type": "integer"}, "followers": {"type": "integer"}, "url": {"type": "string"}},
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
                        "properties": {"repo": {"type": "string"}, "type": {"type": "string"}, "title": {"type": "string"}, "date": {"type": "string"}, "url": {"type": "string"}},
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
                    "properties": {"full_name": {"type": "string"}, "description": {"type": "string"}, "stars": {"type": "integer"}, "forks": {"type": "integer"}, "language": {"type": "string"}, "topics": {"type": "array"}, "readme_excerpt": {"type": "string"}, "url": {"type": "string"}},
                },
            },
        },
    },
    {
        "name": "stdlib",
        "description": "Python standard library utilities — time, random.",
        "handler": "cogos.capabilities.stdlib.stdlib",
        "instructions": (
            "stdlib exposes Python standard library modules.\n"
            "- stdlib.time — Python time module (time.time(), time.sleep(), time.strftime(), etc.)\n"
            "- stdlib.random — Python random module (random.random(), random.randint(), random.choice(), etc.)\n"
        ),
        "schema": {},
    },
    {
        "name": "alerts",
        "description": "Emit system alerts (warnings, errors) to the dashboard.",
        "handler": "cogos.capabilities.alerts.AlertsCapability",
        "instructions": (
            "alerts lets you emit alerts visible in the dashboard.\n"
            "- alerts.warning(alert_type, message, **metadata) — emit a warning\n"
            "- alerts.error(alert_type, message, **metadata) — emit a critical error\n"
        ),
        "schema": {},
    },
    {
        "name": "coglet_factory",
        "description": "Create and manage coglets — long-lived code+tests containers with PR-style patch workflows.",
        "handler": "cogos.capabilities.coglet_factory.CogletFactoryCapability",
        "instructions": (
            "Use coglet_factory to create and manage coglets.\n"
            "- coglet_factory.create(name, test_command, files) — create a new coglet\n"
            "- coglet_factory.list() — list all coglets\n"
            "- coglet_factory.get(coglet_id) — get coglet metadata\n"
            "- coglet_factory.delete(coglet_id) — delete a coglet\n"
            "A coglet wraps code + tests. Use the 'coglet' capability to operate on one."
        ),
        "schema": {},
    },
    {
        "name": "blob",
        "description": "Upload and download files via S3 for cross-capability sharing.",
        "handler": "cogos.capabilities.blob.BlobCapability",
        "instructions": (
            "Use blob to share files between capabilities (discord, email, etc.).\n"
            "- ref = blob.upload(data, filename, content_type?) — upload bytes, get BlobRef with key and URL\n"
            "- content = blob.download(key) — download by key, get BlobContent with data\n"
            "BlobRef.key is the durable identifier. BlobRef.url is a presigned URL (7 day expiry).\n"
            "Blobs are stored in S3 and auto-deleted after 30 days."
        ),
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
    {
        "name": "coglet",
        "description": "Operate on a single coglet — propose patches, inspect files, merge changes.",
        "handler": "cogos.capabilities.coglet.CogletCapability",
        "instructions": (
            "Use coglet to interact with a specific coglet (must be scoped with coglet_id).\n"
            "- coglet.propose_patch(diff) — apply a unified diff, run tests, return results\n"
            "- coglet.merge_patch(patch_id) — promote a passing patch to main (fails if main changed)\n"
            "- coglet.discard_patch(patch_id) — delete a patch branch\n"
            "- coglet.read_file(path, patch_id?) — read a file from main or a patch\n"
            "- coglet.list_files(patch_id?) — list files in main or a patch\n"
            "- coglet.list_patches() — list pending patches with test results\n"
            "- coglet.get_status() — current version, patch count\n"
            "- coglet.run_tests() — run tests on current main\n"
            "- coglet.get_log() — patch history\n"
            "Workflow: propose_patch -> review results -> merge_patch or discard_patch"
        ),
        "schema": {},
    },
]
