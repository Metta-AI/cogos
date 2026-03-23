# CogOS Guide

Practical guide to operating CogOS -- creating images, booting cogents, managing processes, and understanding the runtime.

## Quick Start

### Prerequisites

- AWS credentials configured (your SSO profile from `~/.cogos/cogtainers.yml`)
- Python with `uv` for dependency management
- Environment variables for DB: `DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`, `AWS_REGION`
- For local dev: configure a local cogtainer in `~/.cogos/cogtainers.yml`; the data directory is resolved from the cogtainer config

### Boot a Cogent

```bash
# Boot from an image and start dispatcher
cogos start

# Clean boot (wipes tables first)
cogos start --clean

# Restart (stop + boot + start)
cogos restart
```

### Check Status

```bash
COGENT=<name> cogos process list
COGENT=<name> cogos channel list --limit 20
COGENT=<name> cogos capability list
```

## Images

An image is a directory that declaratively defines a cogent's entire configuration. Think of it like a container image for agent state.

### Structure

```
images/cogos/
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
    content="@{cogos/scheduler.md}",  # inline file reference
    runner="lambda",
    priority=100.0,
    capabilities=["scheduler"],
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

### Content Directories

Every directory at the image root (except `init/` and `apps/`) is scanned for content files. The relative path from the image root becomes the key:

```
cogos/lib/scheduler.md          -> key: "cogos/lib/scheduler.md"
whoami/index.md                 -> key: "whoami/index.md"
cogos/includes/code_mode.md     -> key: "cogos/includes/code_mode.md"
cogos/docs/layout.md            -> key: "cogos/docs/layout.md"
```

The key keeps the original filename suffix.

Files under `cogos/includes/` are automatically prepended to every process's system prompt by the executor.

For the runtime `/proc/{process_id}/...` layout used by `me` and the executor, see [File Store and `/proc` Namespace](file-store.md).

### File References

Files can reference other files inline with `@{...}`. The context engine resolves those references recursively, depth-first:

```python
# In a process definition, use @{...} to reference a file
add_process("my-agent", content="@{agents/my-agent.md}", ...)
```

The file at `agents/my-agent.md` might contain:

```md
@{whoami/index.md}
@{cogos/includes/code_mode.md}
```

Those references are expanded directly where they appear when building the prompt.

### Boot vs Snapshot

**Boot** applies an image to a database. It upserts everything -- creates what's missing, updates what changed, skips what's identical. Non-destructive by default.

**Snapshot** captures a running cogent's state into a new image directory. It queries all capabilities, resources, processes, cron rules, and files from the DB and generates bootable init scripts and file trees.

```bash
# Snapshot running state
cogos snapshot my-snapshot
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
    content="@{agents/data-sync.md}",
    runner="lambda",
    priority=5.0,
    capabilities=["files", "channels", "procs"],
    handlers=["cron:hourly"],
)
```

Via CLI (for ad-hoc work):

```bash
COGENT=<name> cogos process create \
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

Handlers are not a separate message bus and they are not stale in the channel system. A channel is the durable message stream; a handler is the subscription that tells CogOS which daemon should wake up for that stream. In image config, `handlers=["task:completed"]` means "subscribe this process to the `task:completed` channel."

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

When a message is sent to the `task:completed` channel, `scheduler.match_messages()` creates a delivery for this handler and marks the process RUNNABLE.

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

1. **scheduler.match_messages()** -- find undelivered channel messages, match to handlers, create deliveries, wake WAITING processes
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
- `DB_CLUSTER_ARN` -- RDS cluster ARN
- `DB_SECRET_ARN` -- database credentials
- `DB_NAME` -- database name
- `AWS_REGION` -- defaults to us-east-1
- `MAX_TURNS` -- conversation turn limit (default 20)
- `DEFAULT_MODEL` -- fallback model ID

### ECS

Best for long-running, stateful work (software engineering, git, filesystem). Claude Code CLI runs in a Fargate container with an MCP server exposing CogOS capabilities.

The MCP server (`python -m cogos.sandbox.server --process-id <UUID>`) loads the process's capability bindings and exposes `run_code` as an MCP tool. Claude Code connects to it and uses both CogOS capabilities and its native tools.

## CLI Reference

All commands are scoped to a cogent via the `COGENT` env var:

```bash
COGENT=<name> cogos <subcommand>
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

### Start / Stop / Restart

```bash
cogos start [<image>] [--clean] [--skip-boot] [--foreground]
cogos stop
cogos restart [<image>] [--clean]
cogos snapshot <name>
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
# One command: backend + frontend in the background
COGENT=local cogos dashboard start

# Stop / restart
cogos dashboard stop
cogos dashboard reload

# Manual alternative (two terminals):
source dashboard/ports.sh
USE_LOCAL_DB=1 uv run uvicorn cogos.api.app:app --host 0.0.0.0 --port "$DASHBOARD_BE_PORT" --reload
cd dashboard/frontend && npm run dev
```

If the repo root `.env` does not pin `DASHBOARD_BE_PORT` / `DASHBOARD_FE_PORT`, `dashboard/ports.sh` derives a stable port pair from the checkout path so multiple clones can run side by side.

The dashboard reads from the same local data as `cogos`, so boot local state first:

```bash
cogos start --clean
```

### Panels

| Tab | What it shows |
|---|---|
| Overview | Process counts, recent runs, system health |
| Processes | Process list with status, mode, capabilities, handlers |
| Files | File browser with version history and include tree |
| Capabilities | Capability list with method introspection |
| Handlers | Channel subscription list showing which processes wake on which channels |
| Runs | Run history with cost, duration, scope logs |
| Channels | Channel list with message log and causal tree view |
| Cron | Cron rules with toggle switches |

### API Endpoints

All under `/api/cogents/{name}/`:

| Endpoint | Description |
|---|---|
| `/cogos-status` | CogOS overview stats |
| `/processes` | Process list |
| `/files` | File list |
| `/capabilities` | Capability list |
| `/handlers` | Handler list |
| `/channels` | Channel list |
| `/runs` | Run list |
| `/cron` | Cron rules |

## Operational Patterns

### Adding a New Agent

1. Write the prompt as a markdown file in `images/<image>/files/agents/<name>.md`
2. Define the process in `images/<image>/init/processes.py` with capability bindings and channel handlers
3. Boot the image: `cogos restart`
4. Verify: `COGENT=<name> cogos process list`

### Debugging a Failed Process

1. Check run history: `COGENT=<name> cogos run list --process <name> --status failed`
2. Inspect the run: `COGENT=<name> cogos run show <run_id>` (shows error, tokens, duration)
3. Check channels: `COGENT=<name> cogos channel read process:run:failed`
4. Look at CloudWatch logs for the executor Lambda or ECS task

### Updating a Prompt

1. Edit the file in `images/<image>/files/<key>.md`
2. Re-boot the image: `cogos restart`
3. The file store creates a new version only if content changed

Or update at runtime via capability:

```python
files.write("agents/my-agent.md", "updated prompt content")
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
cogos snapshot backup-2026-03-11

# Boot on a different instance
cogos start backup-2026-03-11 --clean
```

This copies the entire configuration (capabilities, processes, files, handlers, cron) but not runtime state (channel messages, runs, conversations).
