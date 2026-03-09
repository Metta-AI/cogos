# CogOS

An operating system for autonomous AI agents.

## Core Concepts

**Task** — A process. The only active entity in the system. Has a lifecycle,
priority, resource requirements, and capabilities. Executes by running a
prompt through an LLM that writes Python against tool proxy objects.

**Memory** — A versioned filesystem. Stores both code (prompt templates) and
data. Tasks reference memory entries for their executable. Tasks interact with
memory at runtime through tools.

**Tool** — A capability. Defines what a task can do. Tools are Python
functions with typed input/output schemas. At runtime, tools are presented as
proxy objects with methods. A task can only invoke tools explicitly bound
to it.

**Event** — A signal. Append-only log in the database. Tasks subscribe to
event patterns. The scheduler matches events to subscriptions and wakes
sleeping tasks.

**Subscription** — A signal handler. Binds a task to an event pattern. When a
matching event arrives, the task becomes eligible to run.

## Task Lifecycle

```
            event match
  WAITING ─────────────────> RUNNABLE
     ^                          │
     │                          ├── resources available ──> RUNNING
     │                          │                             │
     │                          └── resources exhausted ─> BLOCKED
     │                                                       │
     │                          resources freed              │
     │                          BLOCKED ──────> RUNNABLE     │
     │                                                       │
     │  done + daemon ───────────────────────────────────────┘
     │                                                       │
     └───────────────────────────────────────────────────────┘
                                                             │
                              done + one_shot ──> COMPLETED  │
                              failed + retries ──> RUNNABLE  │
                              failed + exhausted -> DISABLED │
```

**Modes:**

- `daemon` — Runs indefinitely. Completes a run, returns to WAITING for the
  next matching event. Must have at least one subscription.
- `one_shot` — Runs once and completes. Cannot have subscriptions.

**Rules:**

- A task processes one event per run, strictly sequential.
- For parallelism, a task spawns child `one_shot` tasks.
- A task that stays RUNNABLE too long gets its effective priority aged upward
  to prevent starvation.

## Execution Model

### Two Meta-Tools

Every task interacts with the system through two meta-tools:

```
search_tools(query: str) -> list[ToolSpec]
```

Discover available tools by keyword. Returns names, descriptions, and
schemas. Keeps LLM context lean — tool definitions are loaded on demand.

```
run_code(code: str) -> Any
```

Execute Python in a sandboxed environment with proxy objects pre-injected
for all tools bound to the task.

### Proxy Objects

Inside `run_code`, tools appear as Python objects with methods. The LLM
writes natural Python.

```python
# Static tools are top-level objects in the sandbox
memory      # .read(key) .search(query) .write(key, content)
tasks       # .list() .get(name) .create(...)
events      # .emit(type, payload) .query(...)
resources   # .check(name)

# Tool calls return proxy objects with methods
config = memory.read("priorities")
print(config.content)
config.update("new priorities")
config.versions()

# Proxy objects can expose nested proxies
task = tasks.get("data-sync")
task.kill()
task.subscriptions.add("github:pr-opened")

# Spawn a child task with delegated capabilities
child = tasks.create(
    name="reindex",
    mode="one_shot",
    code=memory.read("prompts/reindex").id,
    content="Reindex after data-sync failure",
)
```

### Scope

The executor maintains a variable table during each run. Scope starts with
static tool objects and grows as the agent interacts.

```python
@dataclass
class ScopeEntry:
    type: str                           # "Memory", "Task", etc.
    context: dict                       # instance state (IDs, refs)
    methods: list[ToolSpec]             # callable methods
    children: dict[str, ScopeEntry]     # nested attributes
```

Tools control scope through their return value:

```python
@dataclass
class ToolResult:
    content: Any                # value shown to the agent
    scope: dict | null          # variables to add to scope
    release: list[str] | null   # variables to remove from scope
```

- Scope entries are created when a tool returns `scope` additions.
- Released explicitly via `release`, or auto-cleaned at end of run.
- Nested scopes cascade-release with their parent.

### Proxy Generation

A tool's `output_schema` drives proxy generation:

```json
{
  "type": "object",
  "properties": {
    "content": {"type": "string"},
    "id": {"type": "string", "format": "uuid"}
  },
  "methods": {
    "update": {
      "handler": "cogos.tools.memory.update",
      "args": {"content": "string"}
    },
    "versions": {
      "handler": "cogos.tools.memory.versions",
      "args": {}
    }
  }
}
```

The executor reads `methods`, constructs a proxy class, binds handler calls
with the instance `context`, and injects the proxy into the variable table
under the name the agent assigned it.

## Scheduler

The scheduler is a daemon task. It subscribes to `scheduler:tick` events
emitted by a cron job. Its prompt orchestrates scheduling by calling tools.

### Per-Tick Flow

1. **Match events.** Find unmatched events. For each, find enabled
   subscriptions with matching patterns. Create EventDelivery rows. Mark
   WAITING tasks with pending deliveries as RUNNABLE.

2. **Age priorities.** Compute effective priority:
   `effective = task.priority + f(now - task.runnable_since)`.

3. **Check resources.** For each RUNNABLE task, verify required resources have
   capacity. Insufficient -> BLOCKED.

4. **Unblock.** Check BLOCKED tasks. Resources now available -> RUNNABLE.

5. **Select.** Softmax sample from RUNNABLE tasks by effective priority, up to
   available execution slots.

6. **Dispatch.** Invoke the appropriate runner for each selected task.

### Scheduler Tools

```
match_events()           match pending events to subscriptions
select_tasks()           softmax sample from runnable tasks
dispatch_task(task_id)   send to executor
check_resources()        query resource availability
unblock_tasks()          move BLOCKED -> RUNNABLE where possible
kill_task(task_id)       force-terminate a running task
```

## Runners

Both runners use the same sandbox library. The difference is the host
environment and what additional capabilities are available.

### Lambda

Our executor controls the conversation loop directly.

1. Load task, prompt from memory (resolve includes), tool instructions.
2. Build system prompt and user message (task content + event payload).
3. Conversation loop: LLM calls `search_tools` / `run_code`, executor
   handles them, returns results, loops until done.
4. Record run. Validate result against return schema.
5. Transition task state (daemon -> WAITING, one_shot -> COMPLETED).

Good for: reasoning, data operations, API calls, short-lived work.

### ECS

Claude Code CLI runs in a container. The sandbox is exposed as an MCP server.

1. Launch container. MCP server starts, exposing `search_tools` and
   `run_code` based on the task's tool bindings.
2. Claude Code CLI starts with the task's prompt as system instructions and
   content as the initial message.
3. Claude Code uses `run_code` for system interaction (memory, tasks,
   events) and its native tools (bash, files, git) for everything else.
4. On completion, record run. Optionally persist session to S3.

Good for: software engineering, filesystem work, git, long-running sessions.

### Sandbox Library

Shared by both runners:

```
sandbox/
    executor.py     variable table, scope management, code execution
    proxy.py        proxy object generation from output schemas
    server.py       MCP server wrapping search_tools + run_code
```

## Data Model

### Task

```
Task
  id              UUID            PK
  name            str             unique
  mode            enum            daemon | one_shot
  content         str             task-specific payload (argv)
  code            UUID            FK -> Memory (prompt template)
  priority        float           softmax scheduling weight
  resources       list[UUID]      FK -> Resource
  runner          enum            lambda | ecs
  status          enum            WAITING | RUNNABLE | RUNNING
                                  | BLOCKED | COMPLETED | DISABLED
  runnable_since  datetime?       starvation tracking
  parent_task     UUID?           FK -> Task
  return_schema   dict?           JSON Schema for typed output
  max_duration_ms int?            execution timeout
  max_retries     int             default 0
  retry_count     int             resets on success
  retry_backoff_ms int?           delay before retry
  clear_context   bool            ECS: resume session or fresh
  created_at      datetime
  updated_at      datetime
```

### TaskTool

```
TaskTool
  id              UUID            PK
  task            UUID            FK -> Task
  tool            UUID            FK -> Tool
  config          dict?           per-task scoping
  delegatable     bool            passable to spawned children
```

### Subscription

```
Subscription
  id              UUID            PK
  task            UUID            FK -> Task
  event_pattern   str             matched against Event.event_type
  enabled         bool
```

### Event

```
Event
  id              UUID            PK
  event_type      str             hierarchical, e.g. "task:completed:sync"
  source          str             originating component
  payload         dict
  parent_event    UUID?           FK -> Event (causal chain)
  created_at      datetime
```

### EventDelivery

```
EventDelivery
  id              UUID            PK
  event           UUID            FK -> Event
  subscription    UUID            FK -> Subscription
  status          enum            pending | delivered | skipped
  run             UUID?           FK -> Run
  created_at      datetime
```

### Memory

```
Memory
  id              UUID            PK
  key             str             hierarchical path
  created_at      datetime
  updated_at      datetime

MemoryVersion
  id              UUID            PK
  memory          UUID            FK -> Memory
  content         str
  read_only       bool
  source          str             "agent" | "human" | "system"
  is_active       bool
  created_at      datetime
```

### Tool

```
Tool
  id              UUID            PK
  name            str             hierarchical, e.g. "memory/read"
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
  task            UUID            FK -> Task
  event           UUID?           FK -> Event (triggering event)
  conversation    UUID?           FK -> Conversation
  status          enum            running | completed | failed | timeout
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
  event_type      str             event to emit
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
  tool_calls      list[dict]
  memory_ops      list[dict]
  created_at      datetime
```

## Source Structure

```
cogos/
  db/
    models/
      __init__.py
      task.py
      task_tool.py
      subscription.py
      memory.py
      tool.py
      event.py
      event_delivery.py
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
  memory/
    store.py
    context_engine.py
  cli/
    __main__.py
    task.py                 task commands
    subscription.py         subscription commands
    memory.py               memory commands
    tool.py                 tool commands
    event.py                event commands
    resource.py             resource commands
    cron.py                 cron commands
  dashboard/
    app.py
    routers/
      tasks.py
      subscriptions.py
      memory.py
      tools.py
      events.py
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

## Open Questions

1. **Subscription pattern syntax.** Simple glob (`task:completed:*`) or regex
   or JSONPath filters on payload?
2. **Scope persistence.** Should the variable table survive ECS session
   resume, or start fresh each wake?
3. **Tool versioning.** Should TaskTool pin a tool version or always use
   latest?
4. **Resource quantities.** Should `resources` on Task become a join table
   with `amount` per resource?
```
