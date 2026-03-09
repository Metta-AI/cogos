# CogOS

An operating system for autonomous AI agents.

## Core Concepts

**Process** — The only active entity. Has a lifecycle, priority, resource
requirements, and capabilities. Executes by running a prompt through an LLM
that writes Python against capability proxy objects.

**File** — A versioned entry in a hierarchical store. Stores both code (prompt
templates) and data. Processes reference files for their executable. Processes
interact with files at runtime through capabilities.

**Capability** — Defines what a process can do. Capabilities are Python
functions with typed input/output schemas. At runtime, capabilities are
presented as proxy objects with methods. A process can only invoke capabilities
explicitly bound to it.

**Signal** — An append-only log entry. Processes register handlers for signal
patterns. The scheduler matches signals to handlers and wakes sleeping
processes.

**Handler** — Binds a process to a signal pattern. When a matching signal
arrives, the process becomes eligible to run.

## Process Lifecycle

```
            signal match
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

**Modes:**

- `daemon` — Runs indefinitely. Completes a run, returns to WAITING for the
  next matching signal. Must have at least one handler.
- `one_shot` — Runs once and completes. Cannot have handlers.

**Rules:**

- A process handles one signal per run, strictly sequential.
- For parallelism, a process spawns child `one_shot` processes.
- A process that stays RUNNABLE too long gets its effective priority aged
  upward to prevent starvation.
- Preemptible processes can be suspended mid-execution when a higher-priority
  process needs resources. The executor snapshots conversation state, variable
  table, and scope, then resumes later from the snapshot.

## Execution Model

### Two Meta-Capabilities

Every process interacts with the system through two meta-capabilities:

```
search(query: str) -> list[CapabilitySpec]
```

Discover available capabilities by keyword. Returns names, descriptions,
and schemas. Keeps LLM context lean — definitions are loaded on demand.

```
run_code(code: str) -> Any
```

Execute Python in a sandboxed environment with proxy objects pre-injected
for all capabilities bound to the process.

### Proxy Objects

Inside `run_code`, capabilities appear as Python objects with methods. The
LLM writes natural Python.

```python
# Static capabilities are top-level objects in the sandbox
files       # .read(key) .search(query) .write(key, content)
procs       # .list() .get(name) .create(...) .spawn(...)
signals     # .emit(type, payload) .query(...)
resources   # .check(name)

# Capability calls return proxy objects with methods
config = files.read("priorities")
print(config.content)
config.update("new priorities")
config.versions()

# Proxy objects can expose nested proxies
p = procs.get("data-sync")
p.kill()
p.handlers.add("github:pr-opened")

# Spawn a child process with delegated capabilities
child = procs.spawn(
    name="reindex",
    mode="one_shot",
    code=files.read("prompts/reindex").id,
    content="Reindex after data-sync failure",
)

# Human-in-the-loop via signals
signals.emit("approval:requested", {
    "action": "delete staging data",
    "process": "cleanup",
})
# Process goes WAITING, handler on approval:granted wakes it
```

### Scope

The executor maintains a variable table during each run. Scope starts with
static capability objects and grows as the agent interacts.

```python
@dataclass
class ScopeEntry:
    type: str                           # "File", "Process", etc.
    context: dict                       # instance state (IDs, refs)
    methods: list[CapabilitySpec]       # callable methods
    children: dict[str, ScopeEntry]     # nested attributes
```

Capabilities control scope through their return value:

```python
@dataclass
class CapabilityResult:
    content: Any                # value shown to the agent
    scope: dict | null          # variables to add to scope
    release: list[str] | null   # variables to remove from scope
```

- Scope entries are created when a capability returns `scope` additions.
- Released explicitly via `release`, or auto-cleaned at end of run.
- Nested scopes cascade-release with their parent.

### Proxy Generation

A capability's `output_schema` drives proxy generation:

```json
{
  "type": "object",
  "properties": {
    "content": {"type": "string"},
    "id": {"type": "string", "format": "uuid"}
  },
  "methods": {
    "update": {
      "handler": "cogos.capabilities.files.update",
      "args": {"content": "string"}
    },
    "versions": {
      "handler": "cogos.capabilities.files.versions",
      "args": {}
    }
  }
}
```

The executor reads `methods`, constructs a proxy class, binds handler calls
with the instance `context`, and injects the proxy into the variable table
under the name the agent assigned it.

## Scheduler

The scheduler is a daemon process. It registers a handler for
`scheduler:tick` signals emitted by a cron job. Its prompt orchestrates
scheduling by invoking capabilities.

### Per-Tick Flow

1. **Match signals.** Find undelivered signals. For each, find enabled
   handlers with matching patterns. Create SignalDelivery rows. Mark WAITING
   processes with pending deliveries as RUNNABLE.

2. **Age priorities.** Compute effective priority:
   `effective = process.priority + f(now - process.runnable_since)`.

3. **Check resources.** For each RUNNABLE process, verify required resources
   have capacity. Insufficient -> BLOCKED.

4. **Unblock.** Check BLOCKED processes. Resources now available -> RUNNABLE.

5. **Preempt.** If a RUNNABLE process has higher effective priority than a
   running preemptible process, suspend the running process (snapshot state)
   and free its resources.

6. **Select.** Softmax sample from RUNNABLE processes by effective priority,
   up to available execution slots.

7. **Dispatch.** Invoke the appropriate runner for each selected process.

### Scheduler Capabilities

```
match_signals()              match pending signals to handlers
select_processes()           softmax sample from runnable processes
dispatch_process(proc_id)    send to executor
check_resources()            query resource availability
unblock_processes()          move BLOCKED -> RUNNABLE where possible
suspend_process(proc_id)     snapshot and suspend a running process
resume_process(proc_id)      resume from snapshot
kill_process(proc_id)        force-terminate a running process
```

## Runners

Both runners use the same sandbox library. The difference is the host
environment and what additional capabilities are available.

### Lambda

Our executor controls the conversation loop directly.

1. Load process, prompt from file store (resolve includes), capability
   instructions.
2. Build system prompt and user message (process content + signal payload).
3. Conversation loop: LLM calls `search` / `run_code`, executor handles
   them, returns results, loops until done.
4. Record run. Validate result against return schema.
5. Transition process state (daemon -> WAITING, one_shot -> COMPLETED).

Good for: reasoning, data operations, API calls, short-lived work.

### ECS

Claude Code CLI runs in a container. The sandbox is exposed as an MCP server.

1. Launch container. MCP server starts, exposing `search` and `run_code`
   based on the process's capability bindings.
2. Claude Code CLI starts with the process's prompt as system instructions
   and content as the initial message.
3. Claude Code uses `run_code` for system interaction (files, processes,
   signals) and its native capabilities (bash, file editing, git) for
   everything else.
4. On completion, record run. Optionally persist session to S3.

Good for: software engineering, filesystem work, git, long-running sessions.

### Sandbox Library

Shared by both runners:

```
sandbox/
    executor.py     variable table, scope management, code execution
    proxy.py        proxy generation from output schemas
    server.py       MCP server wrapping search + run_code
```

## Preemption

Preemptible processes can be suspended mid-execution to free resources for
higher-priority work.

### Snapshot

When the scheduler suspends a process, the executor captures:

- Conversation messages (system prompt + all turns so far)
- Variable table (all scope entries with context)
- Current turn index
- Pending capability results

This is stored on the Run record:

```
Run.snapshot    dict?       serialized execution state
```

### Resume

When the scheduler resumes a suspended process:

1. Executor loads the snapshot from the Run.
2. Rebuilds conversation state and variable table.
3. Continues the conversation loop from where it left off.

### Rules

- `preemptible: bool` on Process controls whether suspension is allowed.
- Long-running ECS processes are generally not preemptible (stateful
  filesystem, git operations).
- Lambda processes are good candidates for preemption.
- A process can only be suspended between capability calls, not mid-LLM-
  generation.

## Human-in-the-Loop

No special mechanism needed. It falls out naturally from signals:

1. Process emits `approval:requested` signal with details of the action.
2. Process registers a handler for `approval:granted:{process_id}`.
3. Process returns, goes to WAITING.
4. Human reviews in dashboard or channel, approves or rejects.
5. Approval signal emitted, process wakes and proceeds (or handles
   rejection).

This pattern works for any human interaction: approvals, reviews, input
requests, escalations.

## Model Routing

Processes can specify model preferences. The scheduler routes to available
models based on requirements and cost.

```
Process:
  model             str?        preferred model (null = scheduler decides)
  model_constraints  dict?      e.g. {"min_context": 128000, "max_cost_per_1k": 0.01}
```

The scheduler considers model availability, cost, and task complexity when
dispatching. Cheap tasks go to smaller models. Complex tasks go to larger
ones. Explicit `model` overrides scheduler choice.

## Data Model

### Process

```
Process
  id                UUID            PK
  name              str             unique
  mode              enum            daemon | one_shot
  content           str             process-specific payload (argv)
  code              UUID            FK -> File (prompt template)
  priority          float           softmax scheduling weight
  resources         list[UUID]      FK -> Resource
  runner            enum            lambda | ecs
  status            enum            WAITING | RUNNABLE | RUNNING | BLOCKED
                                    | SUSPENDED | COMPLETED | DISABLED
  preemptible       bool            can be suspended for higher-priority work
  runnable_since    datetime?       starvation tracking
  parent_process    UUID?           FK -> Process
  return_schema     dict?           JSON Schema for typed output
  model             str?            preferred LLM model
  model_constraints dict?           model requirements
  max_duration_ms   int?            execution timeout
  max_retries       int             default 0
  retry_count       int             resets on success
  retry_backoff_ms  int?            delay before retry
  clear_context     bool            ECS: resume session or fresh
  created_at        datetime
  updated_at        datetime
```

### ProcessCapability

```
ProcessCapability
  id              UUID            PK
  process         UUID            FK -> Process
  capability      UUID            FK -> Capability
  config          dict?           per-process scoping
  delegatable     bool            passable to spawned children
```

### Handler

```
Handler
  id              UUID            PK
  process         UUID            FK -> Process
  signal_pattern  str             matched against Signal.signal_type
  enabled         bool
```

### Signal

```
Signal
  id              UUID            PK
  signal_type     str             hierarchical, e.g. "process:completed:sync"
  source          str             originating component
  payload         dict
  parent_signal   UUID?           FK -> Signal (causal chain)
  created_at      datetime
```

### SignalDelivery

```
SignalDelivery
  id              UUID            PK
  signal          UUID            FK -> Signal
  handler         UUID            FK -> Handler
  status          enum            pending | delivered | skipped
  run             UUID?           FK -> Run
  created_at      datetime
```

### File

```
File
  id              UUID            PK
  key             str             hierarchical path
  created_at      datetime
  updated_at      datetime

FileVersion
  id              UUID            PK
  file            UUID            FK -> File
  content         str
  read_only       bool
  source          str             "agent" | "human" | "system"
  is_active       bool
  created_at      datetime
```

### Capability

```
Capability
  id              UUID            PK
  name            str             hierarchical, e.g. "files/read"
  handler         str             python dotted path
  input_schema    dict            JSON Schema for arguments
  output_schema   dict?           JSON Schema for return value + methods
  instructions    str             guidance for LLM
  iam_role_arn    str?            scoped IAM access
  enabled         bool
```

### Run

```
Run
  id              UUID            PK
  process         UUID            FK -> Process
  signal          UUID?           FK -> Signal (triggering signal)
  conversation    UUID?           FK -> Conversation
  status          enum            running | completed | failed
                                  | timeout | suspended
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

### Cron

```
Cron
  id              UUID            PK
  expression      str             cron expression
  signal_type     str             signal to emit
  payload         dict
  enabled         bool
```

### Conversation

```
Conversation
  id              UUID            PK
  context_key     str             unique identifier (user ID, thread ID)
  channel_id      str             which channel
  status          enum            active | idle | closed
  cli_session_id  str?            for CLI sessions
  created_at      datetime
  updated_at      datetime
```

### Channel

```
Channel
  id              UUID            PK
  name            str
  channel_type    str             discord | github | gmail | asana | cli
  config          dict
  secret_path     str             Secrets Manager path
  enabled         bool
```

### Alert

```
Alert
  id              UUID            PK
  severity        enum            warning | critical | emergency
  source          str
  message         str
  resolved        bool
  created_at      datetime
  resolved_at     datetime?
```

### Budget

```
Budget
  id              UUID            PK
  period          enum            daily | weekly | monthly
  token_limit     int
  cost_limit_usd  float
  tokens_used     int
  cost_used_usd   float
  period_start    datetime
```

### Trace

```
Trace
  id              UUID            PK
  run             UUID            FK -> Run
  capability_calls list[dict]
  file_ops        list[dict]
  created_at      datetime
```

## Source Structure

```
cogos/
  db/
    models/
      __init__.py
      process.py
      process_capability.py
      handler.py
      file.py
      capability.py
      signal.py
      signal_delivery.py
      run.py
      resource.py
      cron.py
      conversation.py
      channel.py
      alert.py
      budget.py
      trace.py
    repository.py
  executor/
    handler.py              Lambda entry point
  sandbox/
    executor.py             variable table, scope management
    proxy.py                proxy generation from output schemas
    server.py               MCP server for ECS runner
  files/
    store.py
    context_engine.py
  cli/
    __main__.py
    process.py              process commands
    handler.py              handler commands
    file.py                 file commands
    capability.py           capability commands
    signal.py               signal commands
    resource.py             resource commands
    cron.py                 cron commands
  dashboard/
    app.py
    routers/
      processes.py
      handlers.py
      files.py
      capabilities.py
      signals.py
      resources.py
      runs.py
      cron.py
      conversations.py
      channels.py
      alerts.py
      status.py
    frontend/
      ...
  deploy/
    cdk/                    AWS CDK infrastructure
  channels/
    discord.py
    github.py
    gmail.py
    asana.py
    cli.py
```

## Open Questions

1. **Signal pattern syntax.** Simple glob (`process:completed:*`) or regex
   or JSONPath filters on payload?
2. **Scope persistence.** Should the variable table survive ECS session
   resume, or start fresh each wake?
3. **Capability versioning.** Should ProcessCapability pin a capability
   version or always use latest?
4. **Resource quantities.** Should `resources` on Process become a join table
   with `amount` per resource?
5. **Preemption granularity.** Can we snapshot mid-LLM-generation (requires
   beam search tree serialization) or only between capability calls?
