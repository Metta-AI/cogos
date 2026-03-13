# CogOS Guide

Practical guide to operating CogOS -- creating images, booting cogents, managing processes, and understanding the runtime.

## Quick Start

### Prerequisites

- AWS credentials configured (profile `softmax-org`)
- Python with `uv` for dependency management
- Environment variables for DB: `DB_RESOURCE_ARN`, `DB_SECRET_ARN`, `DB_NAME`, `AWS_REGION`
- For local dev: set `USE_LOCAL_DB=1` to use LocalRepository (JSON file at `~/.cogent/local/cogos_data.json`)

### Boot a Cogent

```bash
# Boot from an image (upserts into DB, non-destructive)
cogent dr.alpha cogos image boot cogent-v1

# Clean boot (wipes tables first)
cogent dr.alpha cogos image boot cogent-v1 --clean
```

### Check Status

```bash
cogent dr.alpha cogos process list
cogent dr.alpha cogos channel list --limit 20
cogent dr.alpha cogos capability list
```

## Images

An image is a directory that declaratively defines a cogent's entire configuration. Think of it like a container image for agent state.

### Structure

```
images/cogent-v1/
  init/
    capabilities.py    # registers capabilities
    resources.py       # defines resource pools
    processes.py       # defines processes with bindings
    cron.py            # scheduled channel messages
  files/
    cogos/
      docs/            # CogOS documentation for LLM agents
      includes/        # per-subsystem API references (auto-injected)
      lib/
        scheduler.md   # scheduler daemon prompt
    whoami/
      index.md         # agent identity
  README.md
```

### Writing Init Scripts

Each `.py` file in `init/` is exec'd with builder functions available in the namespace. No imports needed.

**capabilities.py** -- register capability handlers:

```python
# Import and register all built-in capabilities
from cogos.capabilities import BUILTIN_CAPABILITIES

for cap in BUILTIN_CAPABILITIES:
    add_capability(
        cap["name"],
        handler=cap["handler"],
        description=cap.get("description", ""),
        instructions=cap.get("instructions", ""),
        input_schema=cap.get("input_schema"),
        output_schema=cap.get("output_schema"),
    )
```

**processes.py** -- define processes with capability bindings and channel handlers:

```python
# Scheduler daemon -- runs every minute, dispatches other processes
add_process(
    "scheduler",
    mode="daemon",
    content="CogOS scheduler daemon",
    code_key="cogos/scheduler",       # key in files/ directory
    runner="lambda",
    priority=100.0,
    capabilities=[
        "scheduler/match_channel_messages",
        "scheduler/select_processes",
        "scheduler/dispatch_process",
        "scheduler/unblock_processes",
        "scheduler/kill_process",
    ],
    handlers=[],                      # scheduler is invoked by the dispatcher directly
)

# Discord message handler -- wakes on DMs and mentions
add_process(
    "discord-handle-message",
    mode="daemon",
    content="You received a Discord message. Read the channel message payload...",
    runner="lambda",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    priority=10.0,
    capabilities=["discord", "channels", "files"],
    handlers=["io:discord:dm", "io:discord:mention"],
)
```

**resources.py** -- define concurrency and budget pools:

```python
add_resource("lambda-slots", type="pool", capacity=5)
add_resource("ecs-slots", type="pool", capacity=2)
```

**cron.py** -- schedule recurring channel messages:

```python
add_cron("* * * * *", channel="system:tick:minute")
```

### Files Directory

Every file under `files/` becomes a File entry in the store. The relative path from `files/` becomes the key:

```
files/cogos/lib/scheduler.md          -> key: "cogos/lib/scheduler"
files/whoami/index.md                 -> key: "whoami/index"
files/cogos/includes/code_mode.md     -> key: "cogos/includes/code_mode"
files/cogos/docs/layout.md            -> key: "cogos/docs/layout"
```

Files under `cogos/includes/` are automatically prepended to every process's system prompt by the executor.

### File Includes

Files can reference other files using the `includes` field (set during file creation). The context engine resolves includes recursively, depth-first:

```python
# In a process definition, code_key points to a file
# That file's includes are resolved automatically
add_process("my-agent", code_key="agents/my-agent", ...)
```

The file at `agents/my-agent` might have includes `["whoami/index", "cogos/includes/code_mode"]`, and those are prepended to its content when building the prompt.

### Boot vs Snapshot

**Boot** applies an image to a database. It upserts everything -- creates what's missing, updates what changed, skips what's identical. Non-destructive by default.

**Snapshot** captures a running cogent's state into a new image directory. It queries all capabilities, resources, processes, cron rules, and files from the DB and generates bootable init scripts and file trees.

```bash
# Snapshot running state
cogent dr.alpha cogos image snapshot my-snapshot

# List available images
cogent dr.alpha cogos image list
```

## Processes

### Modes

**Daemon** processes run indefinitely. They wake on channel messages, do their work, and go back to WAITING. They must have at least one handler binding them to a channel.

**One-shot** processes run once and complete. They cannot have handlers. Use these for batch jobs, one-time tasks, and child work spawned by daemons.

### Lifecycle States

| State | Meaning |
|---|---|
| WAITING | Sleeping. Wakes when a matching channel message arrives. |
| RUNNABLE | Ready to run. Waiting for the scheduler to dispatch. |
| RUNNING | Currently executing. |
| BLOCKED | Runnable but resources unavailable. |
| SUSPENDED | Preempted mid-execution. State snapshotted. |
| COMPLETED | Finished (one-shot only). |
| DISABLED | Permanently stopped (retries exhausted or manually disabled). |

### Creating Processes

Via image (preferred for stable configuration):

```python
# In images/<name>/init/processes.py
add_process(
    "data-sync",
    mode="daemon",
    code_key="agents/data-sync",
    runner="lambda",
    priority=5.0,
    capabilities=["files", "channels", "procs"],
    handlers=["cron:hourly"],
)
```

Via CLI (for ad-hoc work):

```bash
cogent dr.alpha cogos process create \
  --name data-sync \
  --mode daemon \
  --runner lambda \
  --priority 5.0
```

Via capability at runtime (child processes):

```python
# Inside a running process's run_code
child = procs.spawn(
    name="reindex-chunk-42",
    content="Reindex documents 4200-4299",
)
```

### Model Selection

Processes can target specific models:

```python
add_process(
    "cheap-classifier",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ...
)

add_process(
    "complex-reasoner",
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    ...
)
```

If `model` is not set, the executor uses the default (configurable via `DEFAULT_MODEL` env var).

## Capabilities

### How They Work

1. A `Capability` record in the DB defines the name, handler class, and schemas
2. A `ProcessCapability` record binds a capability to a process
3. At execution time, the handler class is imported and instantiated with `(repo, process_id)`
4. The instance is injected into the sandbox as a named variable (e.g., `files`, `discord`)
5. The LLM writes Python that calls methods on these objects

### Writing a Custom Capability

```python
# src/cogos/capabilities/my_cap.py
from cogos.capabilities.base import Capability
from cogos.db.repository import Repository
from uuid import UUID

class MyCapability(Capability):
    """Does something useful."""

    def do_thing(self, param: str) -> dict:
        """Do the thing."""
        # self.repo is the DB repository
        # self.process_id is the owning process
        result = some_operation(param)
        return {"status": "done", "result": result}
```

Register it in your image:

```python
# init/capabilities.py
add_capability(
    "my_cap",
    handler="cogos.capabilities.my_cap.MyCapability",
    description="Does something useful",
    instructions="Use my_cap.do_thing(param) to do the thing.",
)
```

Bind it to a process:

```python
# init/processes.py
add_process("worker", capabilities=["my_cap", "files", "channels"], ...)
```

### Discovery at Runtime

Processes discover capabilities through the sandbox:

```python
# List all available capabilities
capabilities.list()

# Search by keyword
capabilities.search("discord")

# Get detailed help for a specific capability
discord.help()
```

The `help()` method on each capability auto-generates documentation from method signatures, type hints, docstrings, and Pydantic model schemas.

## Channels

### Channel Names

Channels use hierarchical string names with `:` separators:

```
io:discord:dm
io:discord:mention
io:email:inbound
system:tick:minute
process:scheduler
approval:requested
```

### Sending Messages

From a running process:

```python
channels.send("task:completed", {
    "task_name": "data-sync",
    "records_processed": 1500,
})
```

### Handlers

Handlers bind processes to channels:

```python
# In image init
add_process(
    "on-completion",
    mode="daemon",
    handlers=["task:completed"],
    capabilities=["channels", "files"],
    ...
)
```

When a message is sent to the `task:completed` channel, the scheduler's `match_channel_messages()` creates a delivery for this handler and marks the process RUNNABLE.

### Channel Message Payload in Process Context

When a daemon wakes from a handler match, the triggering channel message is injected into the user message:

```
Channel: task:completed
Payload: {
  "task_name": "data-sync",
  "records_processed": 1500
}
```

### Human-in-the-Loop Pattern

```python
# Process sends approval request to a channel
channels.send("approval:requested", {
    "action": "delete staging data",
    "process": "cleanup",
})
# Process returns, goes to WAITING

# Register handler for approval response
# (configured in image: handlers=["approval:granted:cleanup"])
```

Human approves via dashboard or channel. The approval message wakes the process.

## Scheduler

The scheduler is a daemon process (`scheduler`) that runs every minute. It uses the `scheduler` capability to orchestrate the system.

### Tick Sequence

1. **match_channel_messages()** -- find undelivered channel messages, match to handlers, create deliveries, wake WAITING processes
2. **unblock_processes()** -- check BLOCKED processes, move to RUNNABLE if resources freed
3. **select_processes(slots=3)** -- softmax sample from RUNNABLE by effective priority
4. **dispatch_process(process_id)** -- create Run, transition to RUNNING, invoke runner

### Priority and Starvation

Priority is a float. Higher = more likely to be selected. The scheduler uses softmax sampling, not strict ordering, so lower-priority processes still have a chance.

Starvation prevention: `effective_priority = priority + f(now - runnable_since)`. A process that has been RUNNABLE for a long time gets its effective priority boosted.

### Resource Gating

Processes declare required resources. The scheduler checks availability before dispatch:
- **Pool resources** (e.g., `lambda-slots`): concurrent usage slots
- **Consumable resources** (e.g., `daily-budget`): finite tokens/cost per period

If resources are unavailable, the process transitions to BLOCKED and is rechecked on subsequent ticks.

## Runners

### Lambda

Best for short-lived, stateless work. The executor Lambda receives `{process_id, channel_message_id, run_id}`, loads the process, builds the prompt, and runs a Bedrock converse loop.

Key env vars:
- `DB_CLUSTER_ARN` / `DB_RESOURCE_ARN` -- RDS cluster
- `DB_SECRET_ARN` -- database credentials
- `DB_NAME` -- database name
- `AWS_REGION` -- defaults to us-east-1
- `MAX_TURNS` -- conversation turn limit (default 20)
- `DEFAULT_MODEL` -- fallback model ID

### ECS

Best for long-running, stateful work (software engineering, git, filesystem). Claude Code CLI runs in a Fargate container with an MCP server exposing CogOS capabilities.

The MCP server (`python -m cogos.sandbox.server --process-id <UUID>`) loads the process's capability bindings and exposes `run_code` as an MCP tool. Claude Code connects to it and uses both CogOS capabilities and its native tools.

## CLI Reference

All commands are scoped to a cogent instance:

```bash
cogent <instance> cogos <subcommand>
```

### Process Commands

```bash
cogos process list [--status STATUS]
cogos process get <name>
cogos process create --name NAME --mode MODE --runner RUNNER [--priority N] [--model MODEL]
cogos process enable <name>
cogos process disable <name>
```

### File Commands

```bash
cogos file list [--prefix PREFIX]
cogos file get <key>
cogos file create <key> --content CONTENT
cogos file update <key> --content CONTENT
cogos file delete <key>
cogos file history <key>
```

### Handler Commands

```bash
cogos handler list [--process NAME]
cogos handler add --process NAME --channel CHANNEL
cogos handler remove <id>
cogos handler enable <id>
cogos handler disable <id>
```

### Capability Commands

```bash
cogos capability list
cogos capability get <name>
cogos capability enable <name>
cogos capability disable <name>
```

### Channel Commands

```bash
cogos channel list [--name NAME] [--limit N]
cogos channel send --name NAME [--payload JSON]
cogos channel read <name> [--limit N]
```

### Cron Commands

```bash
cogos cron list
cogos cron add --expression EXPR --channel NAME [--payload JSON]
cogos cron enable <id>
cogos cron disable <id>
cogos cron delete <id>
```

### Image Commands

```bash
cogos image boot <name> [--clean]
cogos image snapshot <name>
cogos image list
```

### Run Commands

```bash
cogos run list [--process NAME] [--status STATUS] [--limit N]
cogos run show <id>
```

## Dashboard

The dashboard provides a web UI for monitoring and managing CogOS. It runs as a FastAPI backend + Next.js frontend.

### Starting Locally

```bash
# One command: backend + frontend against the local JSON repo
cogent local dashboard serve --db local

# Manual alternative:
# Backend (port 8100 by default)
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100 --reload

# Frontend (port 5200 by default)
cd dashboard/frontend && npm run dev
```

The dashboard reads from the same local repo as `cogent local cogos ...`, so boot local state first:

```bash
cogent local cogos image boot cogent-v1 --clean
```

### Panels

| Tab | What it shows |
|---|---|
| Overview | Process counts, recent runs, system health |
| Processes | Process list with status, mode, capabilities, handlers |
| Files | File browser with version history and include tree |
| Capabilities | Capability list with method introspection |
| Handlers | Channel handler list with fire counts |
| Runs | Run history with cost, duration, scope logs |
| Channels | Channel list with message log and causal tree view |
| Cron | Cron rules with toggle switches |

### API Endpoints

All under `/api/cogents/{name}/`:

| Endpoint | Description |
|---|---|
| `/cogos/status` | CogOS overview stats |
| `/cogos/processes` | Process list |
| `/cogos/files` | File list |
| `/cogos/capabilities` | Capability list |
| `/cogos/handlers` | Handler list |
| `/cogos/channels` | Channel list |
| `/cogos/runs` | Run list |
| `/cogos/cron` | Cron rules |

## Operational Patterns

### Adding a New Agent

1. Write the prompt as a markdown file in `images/<image>/files/agents/<name>.md`
2. Define the process in `images/<image>/init/processes.py` with capability bindings and channel handlers
3. Boot the image: `cogent <instance> cogos image boot <image>`
4. Verify: `cogent <instance> cogos process list`

### Debugging a Failed Process

1. Check run history: `cogent <instance> cogos run list --process <name> --status failed`
2. Inspect the run: `cogent <instance> cogos run show <run_id>` (shows error, tokens, duration)
3. Check channels: `cogent <instance> cogos channel read process:run:failed`
4. Look at CloudWatch logs for the executor Lambda or ECS task

### Updating a Prompt

1. Edit the file in `images/<image>/files/<key>.md`
2. Re-boot the image: `cogent <instance> cogos image boot <image>`
3. The file store creates a new version only if content changed

Or update at runtime via capability:

```python
files.write("agents/my-agent", "updated prompt content")
```

### Cost Control

- Set `model` on processes to route cheap tasks to Haiku
- Use pool resources to limit concurrent Lambda/ECS executions
- Monitor via `Budget` tracking (daily/weekly/monthly token and cost limits)
- Set `max_duration_ms` to kill runaway processes
- Set `max_retries` to prevent infinite failure loops

### Snapshot and Restore

```bash
# Capture current state
cogent dr.alpha cogos image snapshot backup-2026-03-11

# Boot on a different instance
cogent dr.beta cogos image boot backup-2026-03-11 --clean
```

This copies the entire configuration (capabilities, processes, files, handlers, cron) but not runtime state (channel messages, runs, conversations).
