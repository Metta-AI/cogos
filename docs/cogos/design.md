# CogOS Design

A cluster-level operating system for running many LLM-powered agents safely. CogOS uses capabilities and a DB-backed filesystem to provide process isolation, resource management, and structured inter-agent communication.

## Philosophy

CogOS maps classical OS concepts onto the problem of running many autonomous LLM agents on shared infrastructure:

| OS Concept | CogOS Equivalent | Why |
|---|---|---|
| Process | Process | Agents are long-lived entities with lifecycles, priorities, and resource requirements. |
| Filesystem | File Store | Agents need persistent, versioned, shared storage for prompts, configs, and working data. |
| Syscall / capability | Capability | Agents must be sandboxed. All side effects go through typed, auditable capability calls. |
| Signal | Channel message | Agents communicate asynchronously through typed, append-only channels. |
| Scheduler | Scheduler daemon | A dedicated process matches channel messages to handlers, manages resources, and dispatches work. |
| Container image | Image | Declarative snapshots of a cogent's entire configuration, bootable and restorable. |

The key insight: LLM agents can't be trusted with raw system access. CogOS interposes a capability layer between agent code and the outside world. Every action an agent takes is mediated, typed, logged, and revocable.

## Core Abstractions

### Process

The only active entity. A process has a lifecycle, priority, resource requirements, and a set of bound capabilities. It executes by running a prompt through an LLM that writes Python against capability proxy objects.

```
Process
  id              UUID            PK
  name            str             unique
  mode            enum            daemon | one_shot
  content         str             system prompt source; supports `@{file-key}`
  priority        float           softmax scheduling weight
  resources       list[UUID]      FK -> Resource
  runner          enum            lambda | ecs
  status          enum            WAITING | RUNNABLE | RUNNING | BLOCKED
                                  | SUSPENDED | COMPLETED | DISABLED
  preemptible     bool            can be suspended for higher-priority work
  model           str?            preferred LLM model
  model_constraints dict?         e.g. {"min_context": 128000}
  max_duration_ms int?            execution timeout
  max_retries     int             default 0
  retry_count     int             resets on success
  retry_backoff_ms int?           delay before retry
  clear_context   bool            ECS: resume session or start fresh
  parent_process  UUID?           FK -> Process
  return_schema   dict?           JSON Schema for typed output
  metadata        dict?           arbitrary metadata
  runnable_since  datetime?       starvation tracking
  created_at      datetime
  updated_at      datetime
```

**Modes:**

- `daemon` -- runs indefinitely. Completes a run, returns to WAITING for the next matching channel message. If more deliveries are already pending when a run finishes, it returns directly to RUNNABLE instead of WAITING. Must have at least one handler.
- `one_shot` -- runs once and completes. Cannot have handlers.

**Lifecycle:**

```
            channel message match
  WAITING ─────────────────> RUNNABLE
     ^                          |
     |                          |-- resources available --> RUNNING
     |                          |                             |
     |                          '-- resources exhausted --> BLOCKED
     |                                                       |
     |                          resources freed              |
     |                          BLOCKED ------> RUNNABLE     |
     |                                                       |
     |                       preempted                       |
     |                       RUNNING --------> SUSPENDED     |
     |                       SUSPENDED ------> RUNNABLE      |
     |                                                       |
     |  done + daemon -----------------------------------------------+
     |                                                       |
     '-------------------------------------------------------+
                                                             |
                              done + one_shot --> COMPLETED  |
                              failed + retries --> RUNNABLE  |
                              failed + exhausted -> DISABLED |
```

**Rules:**

- A process handles one channel message per run, strictly sequential.
- For parallelism, a process spawns child `one_shot` processes.
- A process that stays RUNNABLE too long gets its effective priority aged upward to prevent starvation.
- Preemptible processes can be suspended between capability calls (not mid-generation).
- Delivery creation is idempotent per `(channel_message, handler)`. Handler matching may be retried, but duplicate deliveries are not created.
- A dispatched run is authoritative. The executor must use the scheduler's `run_id`; it must not create a replacement run for the same delivery.

## Channel Message Wakeup Path

New external channel messages should not wait for the minute scheduler tick before they become runnable.

### Source of truth

`cogos_channel_message` is the authoritative append-only message log, scoped by channel.

### Hot path

For normal external messages such as Discord DMs:

1. A producer appends a row to `cogos_channel_message`.
2. Handlers bound to that channel are matched.
3. The producer-side repository sends a coalesced, best-effort wake nudge to the per-cogent ingress queue.
4. The ingress Lambda drains a batch, loads the corresponding committed channel messages, matches handlers, creates delivery rows idempotently, marks affected WAITING processes RUNNABLE, creates runs, and invokes executors immediately.

### Coalesced wakeups

The queue message is only a wake signal. It is not the source of truth and does not carry authoritative work state.

At higher message rates we do not want one queue message per channel message. Instead:

- Postgres records the most recent ingress wake request in `cogos_ingress_wake`
- wake requests are coalesced inside a short cooldown window
- the ingress Lambda drains as many pending messages as it can in a batch

This means bursts of channel messages still produce a small number of wake messages while pending deliveries remain the real pending-work set.

### Backstop path

The minute dispatcher remains in place, but its role is different:

- generate virtual `system:tick:*` messages
- reconcile missed or stuck deliveries
- catch legacy or unreconciled messages
- dispatch any remaining runnable processes

The minute dispatcher is a reconciliation loop, not the expected hot path for fresh external messages.

### Dispatch invariants

The scheduler and ingress path rely on these invariants:

- a process transitions to RUNNING only when the scheduler has decided to dispatch it
- the delivery attached to that dispatch moves `pending -> queued -> delivered`
- the executor loads the provided `run_id` instead of synthesizing a new one
- when a daemon run completes, the process returns to RUNNABLE if additional deliveries are already pending, otherwise WAITING

These rules keep channel message, delivery, and run accounting stable even when ingress and reconciliation paths overlap.

### File

A versioned entry in a hierarchical key-value store. Stores both code (prompt templates) and data. Processes reference files for their executable prompt. Processes interact with files at runtime through the `files` capability.

```
File
  id              UUID            PK
  key             str             hierarchical path (e.g. "cogos/scheduler.md")
  includes        list[str]       keys of other files to include in context
  created_at      datetime
  updated_at      datetime

FileVersion
  id              UUID            PK
  file_id         UUID            FK -> File
  version         int             monotonic
  content         str
  read_only       bool
  source          str             "agent" | "human" | "system"
  is_active       bool
  created_at      datetime
```

Files support prompt references via inline `@{file-key}` syntax. When a file is resolved into prompt context, the context engine recursively expands those references, depth-first, concatenating content with section headers. Circular references are detected and reported.

For the runtime `/proc/{process_id}/...` namespace, including executor-owned session artifacts under `_sessions/`, see [File Store and `/proc` Namespace](file-store.md).

### Capability

Defines what a process can do. Capabilities are Python classes with typed methods. At runtime, capabilities are instantiated per-process with a repository handle and the owning process ID, then injected into the sandbox as proxy objects.

```
Capability
  id              UUID            PK
  name            str             e.g. "files", "procs", "discord"
  handler         str             Python dotted path to class
  description     str
  instructions    str             guidance injected into system prompt
  input_schema    dict            JSON Schema per method
  output_schema   dict?           JSON Schema per method
  iam_role_arn    str?            scoped IAM access
  metadata        dict?
  enabled         bool
```

**Built-in capabilities:**

| Name | Purpose |
|---|---|
| `files` | Versioned file store (read, write, search) |
| `procs` | Process management (list, get, spawn) |
| `channels` | Channel messaging (send, read, create, list) |
| `schemas` | Schema definitions (get, list) |
| `resources` | Resource pool queries |
| `me` | Scoped scratch/tmp/log storage per process and run |
| `secrets` | AWS SSM / Secrets Manager retrieval |
| `scheduler` | Channel message matching, process selection, dispatch (scheduler only) |
| `discord` | Discord messaging, reactions, threads, DMs |
| `email` | SES send/receive |

### ProcessCapability

Binds a capability to a process with optional per-process scoping and delegation control.

```
ProcessCapability
  id              UUID            PK
  process         UUID            FK -> Process
  capability      UUID            FK -> Capability
  config          dict?           per-process scoping
  delegatable     bool            passable to spawned children
```

When a process spawns a child, only capabilities marked `delegatable=true` on the parent can be granted to the child.

### Channel

A typed, append-only message stream with a defined schema and an owner.

```
Channel
  id              UUID            PK
  name            str             hierarchical (e.g. "io:discord:dm", "process:scheduler")
  owner_process   UUID?           FK -> Process
  schema_id       UUID?           FK -> Schema
  inline_schema   dict?           inline schema definition
  channel_type    str             'implicit' | 'spawn' | 'named'
  auto_close      bool            default false
  closed_at       datetime?
  created_at      datetime
```

### Schema

Defines the structure of messages on a channel.

```
Schema
  id              UUID            PK
  name            str             e.g. "metrics", "discord_message"
  definition      dict            JSON schema definition
  file_id         UUID?           FK -> File
  created_at      datetime
```

### ChannelMessage

An append-only message on a channel.

```
ChannelMessage
  id              UUID            PK
  channel         UUID            FK -> Channel
  sender_process  UUID?           FK -> Process
  payload         dict
  created_at      datetime
```

### Handler

Binds a process to a channel. In the channel model, handlers are subscriptions and wakeup bindings, not a separate event transport. When a matching message arrives on that channel, the process becomes eligible to run.

```
Handler
  id              UUID            PK
  process         UUID            FK -> Process
  channel         UUID            FK -> Channel (bound channel)
  enabled         bool
  created_at      datetime
```

### Delivery

Per-handler delivery tracking. One idempotent row per channel message per matching handler.

```
Delivery
  id              UUID            PK
  message         UUID            FK -> ChannelMessage
  handler         UUID            FK -> Handler
  status          enum            pending | queued | delivered | skipped
  run             UUID?           FK -> Run
  created_at      datetime
```

### Run

Execution record for a single process invocation.

```
Run
  id              UUID            PK
  process         UUID            FK -> Process
  channel_message UUID?           FK -> ChannelMessage (triggering message)
  conversation    UUID?           FK -> Conversation
  status          enum            running | completed | failed | timeout | suspended
  snapshot        dict?           serialized state for preemption resume
  tokens_in       int
  tokens_out      int
  cost_usd        float
  duration_ms     int
  error           str?
  model_version   str
  result          dict?           typed output
  scope_log       list[dict]      audit trail of scope changes
  created_at      datetime
```

### Resource

Pool (concurrency) and consumable (budget) limits.

```
Resource
  id              UUID            PK
  name            str
  resource_type   enum            pool | consumable
  capacity        float
  metadata        dict

ResourceUsage
  id              UUID            PK
  resource        UUID            FK -> Resource
  run             UUID            FK -> Run
  amount          float
  created_at      datetime
```

### Supporting Models

- **Cron** -- scheduled message emitter (expression, channel, payload, enabled)
- **Conversation** -- multi-turn context routing for channels
- **Alert** -- algedonic system (warning / critical / emergency)
- **Budget** -- token and cost accounting per period
- **Trace** -- detailed execution audit (capability calls, file ops per run)

## Execution Model

### Two Meta-Capabilities

Every process, regardless of runner, interacts with the system through two meta-capabilities exposed to the LLM:

```
search(query: str) -> list[CapabilitySpec]
```

Discover available capabilities by keyword. Returns names, descriptions, and schemas. Keeps LLM context lean -- definitions are loaded on demand.

```
run_code(code: str) -> Any
```

Execute Python in a sandboxed environment with proxy objects pre-injected for all capabilities bound to the process.

### Proxy Objects

Inside `run_code`, capabilities appear as Python objects with methods. The LLM writes natural Python:

```python
# Static capabilities are top-level objects in the sandbox
files       # .read(key) .write(key, content) .search(prefix)
procs       # .list() .get(name) .spawn(name, content)
channels    # .send(channel, payload) .read(channel, limit?) .create(name, schema)
resources   # .check()
me          # .run() .process() -- scoped storage

# Capability methods return dicts or proxy objects
config = files.read("priorities")
print(config["content"])

# Spawn a child process
child = procs.spawn(
    name="reindex",
    content="Reindex after data-sync failure",
)

# Human-in-the-loop via channels
channels.send("approval:requested", {
    "action": "delete staging data",
    "process": "cleanup",
})
```

### Sandbox

The `SandboxExecutor` manages a `VariableTable` of named objects. Capability proxies are injected at startup. A `CapabilitiesDirectory` is also injected for runtime discovery (`capabilities.list()`, `capabilities.search(query)`, `<name>.help()`).

Code execution happens in a restricted namespace. The executor captures stdout and returns it as the tool result. Exceptions are caught and returned as error tracebacks.

### Context Engine

The `ContextEngine` resolves prompt context from inline references:

1. Expand any `@{file-key}` references found in `process.content`
2. For each referenced file:
   - Recursively resolve `file.includes` depth-first
   - Recursively expand any nested `@{file-key}` references in file content
   - Concatenate with `--- key ---` section headers
3. Prepend all files under `cogos/includes/` as global context

This is used by both the Lambda executor (system prompt) and the dashboard (prompt preview).

## Runners

### Lambda Runner

Our executor controls the full Bedrock converse API loop:

1. Load process from DB
2. Build system prompt via ContextEngine (resolve includes, prepend global includes)
3. Build user message from the triggering channel payload
4. Inject `search` and `run_code` as Bedrock tool definitions
5. Conversation loop (max N turns):
   - LLM returns tool_use for `search` or `run_code`
   - Execute in sandbox with proxy objects
   - Return results to LLM
   - Loop until stop_reason != tool_use
6. Record Run (tokens, cost, duration, result, scope_log)
7. Transition process: daemon -> RUNNABLE if more deliveries are pending, otherwise WAITING; one_shot -> COMPLETED
8. On failure: increment retry_count, backoff, or DISABLED

Good for: reasoning, data operations, API calls, short-lived work.

### ECS Runner

Claude Code CLI runs in a container. Capabilities are exposed as an MCP server:

1. Launch ECS task
2. MCP server starts (`cogos.sandbox.server`), reads process's capability bindings
3. Exposes `run_code` as an MCP tool with capability proxies pre-injected
4. Claude Code CLI starts with the process's prompt as system instructions
5. Claude Code uses `run_code` for CogOS interaction and its native tools (bash, file editing, git) for everything else
6. On completion, record Run

Good for: software engineering, filesystem work, git, long-running sessions.

### Shared Sandbox Library

Both runners use the same core library:

```
cogos/sandbox/
    executor.py     # VariableTable, SandboxExecutor, code execution
    server.py       # MCP server wrapping run_code (for ECS)
```

## Scheduler

The scheduler is itself a daemon process. It registers for `system:tick:minute` messages and runs the scheduling loop using the `scheduler` capability.

### Per-Tick Flow

1. **scheduler.match_messages()** -- scan undelivered channel messages, match to handlers by channel, create delivery rows. Mark WAITING processes with pending deliveries as RUNNABLE.

2. **unblock_processes()** -- check BLOCKED processes. Resources now available -> RUNNABLE.

3. **select_processes(slots)** -- softmax sample from RUNNABLE processes by effective priority. Priority aging prevents starvation.

4. **dispatch_process(process_id)** -- transition to RUNNING, create a Run record, invoke the appropriate runner (Lambda invocation or ECS task start).

### System Tick Messages

The dispatcher generates virtual tick messages (not written to channels):
- `system:tick:minute` -- every invocation
- `system:tick:hour` -- when minute == 0

Processes can register handlers for these to run periodically.

## Image System

An image is a declarative snapshot of a cogent's entire configuration. Images are directories of Python scripts and files that define the initial state.

### Image Structure

```
images/<name>/
  init/
    capabilities.py    # add_capability() calls
    resources.py       # add_resource() calls
    processes.py       # add_process() calls
    cron.py            # add_cron() calls
  files/
    cogos/
      docs/            # CogOS documentation for LLM agents
      includes/        # per-subsystem API references (auto-injected)
      lib/
        scheduler.md   # scheduler daemon prompt
    whoami/
      index.md
  README.md
```

Each `.py` in `init/` is exec'd with builder functions injected into its namespace:

```python
add_capability(name, *, handler, description="", instructions="", input_schema=None, output_schema=None, iam_role_arn=None, metadata=None)
add_resource(name, *, type, capacity, metadata=None)
add_schema(name, *, definition)
add_channel(name, *, schema=None, channel_type="named")
add_process(name, *, mode="one_shot", content="", runner="lambda", model=None, priority=0.0, capabilities=None, handlers=None, metadata=None)
add_cron(expression, *, channel, payload=None, enabled=True)
```

All calls accumulate into an `ImageSpec` dataclass. `load_image(path) -> ImageSpec` handles execution.

### Boot Sequence

1. Run DB migrations
2. If `--clean`: truncate all CogOS tables
3. Upsert capabilities by name
4. Upsert schemas by name
5. Upsert channels by name
6. Upsert resources by name
7. Upsert cron rules
8. Upsert files via FileStore (creates if new, new version if changed, skips if unchanged)
9. Upsert processes by name, bind capabilities, create handlers

### Snapshot

Captures running state into a new image directory. Queries all capabilities, resources, processes (with bindings + handlers), cron rules, schemas, channels, and files (active version only). Generated images are immediately bootable.

### What Gets Captured

Config only:
- Capabilities, resources, processes (with capability bindings and channel subscriptions)
- Schemas, channels, cron rules, files (active version content only)

Not captured: channel messages, runs, traces, conversations, file version history.

## Human-in-the-Loop

No special mechanism. It falls out naturally from channels:

1. Process sends a message to `approval:requested` channel with action details
2. Process registers handler for `approval:granted:{process_id}` channel
3. Process returns, goes to WAITING
4. Human reviews in dashboard or channel, approves or rejects
5. Approval message sent, process wakes and proceeds (or handles rejection)

This pattern works for any human interaction: approvals, reviews, input requests, escalations.

## Model Routing

Processes can specify model preferences:

```
Process:
  model             str?        preferred model (null = scheduler decides)
  model_constraints  dict?      {"min_context": 128000, "max_cost_per_1k": 0.01}
```

The executor uses `process.model` if set, otherwise falls back to a configurable default (currently Sonnet). Cheap tasks can target Haiku; complex tasks target Opus.

## Infrastructure

### AWS Resources

- **RDS PostgreSQL** -- all CogOS tables via RDS Data API
- **Lambda** -- executor function for Lambda-runner processes
- **ECS** -- Fargate tasks for ECS-runner processes
- **ECR** -- container images for ECS tasks
- **Secrets Manager / SSM** -- credential storage
- **CloudWatch** -- logging and run monitoring

### Database

All state lives in PostgreSQL, accessed via RDS Data API. Tables are prefixed with `cogos_` (process, handler, channel, channel_message, delivery, file, file_version, capability, process_capability, run, resource, resource_usage, schema, cron, conversation, alert, budget, trace).

Channel messages are DB records matched by the scheduler -- no external event bus (EventBridge was eliminated).

## Source Structure

```
src/cogos/
  capabilities/
    __init__.py         # BUILTIN_CAPABILITIES registry
    base.py             # Capability base class with help() introspection
    directory.py        # CapabilitiesDirectory for runtime discovery
    files.py            # FilesCapability
    procs.py            # ProcsCapability
    channels.py         # ChannelsCapability
    schemas.py          # SchemasCapability
    resources.py        # ResourcesCapability
    me.py               # MeCapability (scoped scratch/tmp/log)
    secrets.py          # SecretsCapability (SSM/Secrets Manager)
    scheduler.py        # SchedulerCapability
  io/
    discord/            # Discord bridge + DiscordCapability
    email/              # SES integration + EmailCapability
    github/             # GitHub integration (planned)
  db/
    models/             # Pydantic models (one per entity)
    repository.py       # CRUD via RDS Data API
    local_repository.py # JSON-file backend for local dev
    migrations/         # SQL migration files
  executor/
    handler.py          # Lambda entry point + Bedrock converse loop
  sandbox/
    executor.py         # VariableTable, SandboxExecutor
    server.py           # MCP server for ECS runner
  files/
    store.py            # FileStore (versioned operations)
    context_engine.py   # Include resolution for prompts
  image/
    spec.py             # ImageSpec, load_image()
    apply.py            # apply_image() (boot/upsert into DB)
    design.md
  cli/
    __main__.py         # CLI entry point (process, handler, file, capability, channel, cron, image)
```

## Security Model

### Capability Isolation

Processes can only invoke capabilities explicitly bound to them via ProcessCapability. There is no ambient authority. A process that needs to send Discord messages must have the `discord` capability bound; one that doesn't, can't.

### Delegation Control

When spawning child processes, parents can only delegate capabilities marked `delegatable=true`. This prevents privilege escalation through process spawning.

### Sandbox Restrictions

The `run_code` sandbox executes in a controlled namespace. Only capability proxy objects and basic Python builtins are available. No file system access, no network access, no imports beyond what capabilities expose.

### Audit Trail

Every capability call, file operation, and channel message is tracked:
- `Run.scope_log` records scope changes during execution
- `Trace` records detailed capability calls and file ops
- `Delivery` tracks which channel messages were delivered to which handlers
- `FileVersion` maintains full history of every file change

### Resource Limits

Processes declare resource requirements. The scheduler enforces limits:
- Pool resources (concurrency slots) prevent runaway parallelism
- Consumable resources (token budgets) prevent cost overruns
- `max_duration_ms` hard-kills processes that run too long
- `max_retries` with backoff prevents infinite failure loops

## Open Questions

1. **Channel subscription syntax.** Currently handler binds to a channel directly. Glob patterns on channel names (`io:discord:*`)? JSONPath filters on payload?
2. **Scope persistence.** Should the variable table survive ECS session resume, or start fresh each wake?
3. **Capability versioning.** Should ProcessCapability pin a capability version or always use latest?
4. **Preemption granularity.** Can we snapshot mid-LLM-generation, or only between capability calls?
