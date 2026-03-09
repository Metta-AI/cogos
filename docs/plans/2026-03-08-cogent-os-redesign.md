# Cogent OS Redesign

Date: 2026-03-08
Status: Draft

## Motivation

The current architecture has redundant abstractions. Programs are executable
templates stored outside memory for no good reason. Triggers wire events to
programs through an indirection layer. The dispatcher publishes events to
EventBridge when a simple DB query would suffice. The executor has two code
paths (prompt and python) that can be unified.

This redesign reframes the architecture using OS primitives:

| OS Concept | Cogent Equivalent |
|---|---|
| Process | Task |
| Filesystem | Memory |
| Capability / syscall | Tool |
| Signal | Event |
| Scheduler | Daemon task with scheduler tools |

Programs and Triggers are eliminated. Everything reduces to tasks interacting
with memory and tools.

## Design Principles

1. **Tasks are processes.** They have a lifecycle, priority, resource
   requirements, and capabilities. They are the only active entity.
2. **Memory is a filesystem.** It stores both code (prompt templates) and data.
   Tasks reference memory for their executable and interact with it via tools
   at runtime.
3. **Tools are capabilities.** All programmatic logic lives in tools. There is
   no `exec()` code path. Execution is always prompt-based: LLM writes Python
   that calls tool proxy objects.
4. **Events are signals.** Append-only log in the database. Tasks subscribe to
   event patterns. The scheduler matches events to subscriptions. No external
   event bus.
5. **One execution model.** Both Lambda and ECS runners use the same two
   meta-tools (`search_tools` and `run_code`). The LLM always writes Python
   against proxy objects. The sandbox is a library, not a deployment unit.

## Data Model

### Task

The central entity. A process with a lifecycle, priority, and capabilities.

```
Task:
  id: UUID                          PK
  name: str                         unique
  mode: daemon | one_shot           daemon loops; one_shot completes
  content: str                      argv -- task-specific payload
  code: UUID                        FK -> Memory.id (prompt template)
  priority: float                   softmax scheduling weight
  resources: list[UUID]             FK -> Resource.id
  runner: lambda | ecs
  status: enum                      WAITING | RUNNABLE | RUNNING | BLOCKED
                                    | COMPLETED | DISABLED
  runnable_since: datetime | null   set on RUNNABLE, cleared on RUNNING
  parent_task: UUID | null          FK -> Task.id
  return_schema: dict | null        JSON Schema for typed output
  max_duration_ms: int | null       executor kills after this
  max_retries: int                  default 0
  retry_count: int                  current failures, resets on success
  retry_backoff_ms: int | null      delay before re-entering RUNNABLE
  clear_context: bool               ECS only: resume S3 session or fresh
  created_at: datetime
  updated_at: datetime
```

State machine:

```
WAITING  -- event match ----------> RUNNABLE
RUNNABLE -- resources available --> RUNNING
RUNNABLE -- resources exhausted --> BLOCKED
BLOCKED  -- resources freed ------> RUNNABLE
RUNNING  -- done + daemon --------> WAITING
RUNNING  -- done + one_shot ------> COMPLETED
RUNNING  -- failed + retries -----> RUNNABLE (after backoff)
RUNNING  -- failed + exhausted ---> DISABLED
```

Rules:
- `one_shot` tasks cannot have subscriptions.
- Daemons process one event per run, strictly sequential.
- For parallelism, spawn child `one_shot` tasks via tools.

### TaskTool

Join table binding tools to tasks with per-task scoping and capability
delegation.

```
TaskTool:
  id: UUID                PK
  task: UUID              FK -> Task.id
  tool: UUID              FK -> Tool.id
  config: dict | null     per-task scoping passed to handler at runtime
  delegatable: bool       can this tool be passed to spawned children?
```

When a task spawns a child via `tasks.create()`, only tools marked
`delegatable=true` on the parent can be granted to the child.

### Subscription

Daemons register interest in event patterns. Replaces the Trigger table.

```
Subscription:
  id: UUID                PK
  task: UUID              FK -> Task.id
  event_pattern: str      matched against Event.event_type
  enabled: bool
```

### Event

Append-only signal log. No lifecycle status (no proposed/sent).

```
Event:
  id: UUID                PK
  event_type: str         hierarchical, e.g. "task:completed:data-sync"
  source: str             originating component
  payload: dict
  parent_event: UUID      FK -> Event.id (causal chain)
  created_at: datetime
```

### EventDelivery

Per-subscription delivery tracking. One row per event per matching
subscription.

```
EventDelivery:
  id: UUID                PK
  event: UUID             FK -> Event.id
  subscription: UUID      FK -> Subscription.id
  status: enum            pending | delivered | skipped
  run: UUID | null        FK -> Run.id (which run processed this)
  created_at: datetime
```

### Memory

Versioned key-value store. Now also stores task code (prompt templates).

```
Memory:
  id: UUID                PK
  key: str                hierarchical path, e.g. "vsm/s1/do-content"
  created_at: datetime
  updated_at: datetime

MemoryVersion:
  id: UUID                PK
  memory: UUID            FK -> Memory.id
  content: str
  read_only: bool
  source: str             "cogent" | "human" | "system"
  is_active: bool
  created_at: datetime
```

### Tool

Capability definition with input and output schemas.

```
Tool:
  id: UUID                PK
  name: str               hierarchical, e.g. "memory/read", "tasks/create"
  handler: str            python dotted path, e.g. "brain.tools.memory.read"
  input_schema: dict      JSON Schema for arguments
  output_schema: dict     JSON Schema for return value
  instructions: str       guidance injected into system prompt
  iam_role_arn: str       optional scoped IAM access
  enabled: bool
```

`output_schema` drives proxy object generation. The executor uses it to
determine what methods and attributes to expose on returned proxy objects.

### Run

Execution record for a single task invocation.

```
Run:
  id: UUID                PK
  task: UUID              FK -> Task.id
  event: UUID | null      FK -> Event.id (triggering event)
  conversation: UUID      FK -> Conversation.id
  status: enum            running | completed | failed | timeout
  tokens_in: int
  tokens_out: int
  cost_usd: float
  duration_ms: int
  error: str | null
  model_version: str
  result: dict | null     typed output, validated against task.return_schema
  scope_log: list[dict]   audit trail of scope changes during execution
  created_at: datetime
```

### Resource

Pool (concurrency) and consumable (budget) limits.

```
Resource:
  id: UUID                PK
  name: str
  resource_type: enum     pool | consumable
  capacity: float
  metadata: dict

ResourceUsage:
  id: UUID                PK
  resource: UUID          FK -> Resource.id
  run: UUID               FK -> Run.id
  amount: float
  created_at: datetime
```

### Cron

Scheduled event emitter.

```
Cron:
  id: UUID                PK
  expression: str         cron expression
  event_type: str         event to emit on each tick
  payload: dict
  enabled: bool
```

### Unchanged Models

These models carry over from the current design without structural changes:

- **Conversation** -- multi-turn context routing for channels
- **Channel** -- external integrations (Discord, GitHub, Gmail, Asana, CLI)
- **Alert** -- algedonic system (warning / critical / emergency)
- **Budget** -- token and cost accounting per period
- **Trace** -- detailed execution audit (tool calls, memory ops per run)

## Execution Model

### Two Meta-Tools

Every task, regardless of runner, interacts with the system through two
meta-tools exposed to the LLM:

```
search_tools(query: str) -> list[ToolSpec]
    Discover available tools by keyword. Returns tool names, descriptions,
    and schemas. Keeps context lean -- the LLM only loads tool definitions
    it needs.

run_code(code: str) -> Any
    Execute Python code in a sandboxed environment. The sandbox has proxy
    objects pre-injected for all tools bound to the task via TaskTool.
```

### Proxy Object Model

Inside `run_code`, tools are exposed as Python objects with methods. The LLM
writes natural Python, not JSON tool calls.

Static tools (from TaskTool) are top-level objects:

```python
memory      # .read(key), .search(query), .write(key, content)
tasks       # .list(), .get(name), .create(...)
events      # .emit(type, payload), .query(...)
resources   # .check(name)
```

Tool calls return proxy objects with methods. Scope grows as the agent
interacts:

```python
# memory.read returns a Memory proxy
config = memory.read("vsm/priorities")
print(config.content)
config.update("new priorities")
config.versions()

# tasks.get returns a Task proxy
sync = tasks.get("data-sync")
sync.kill()

# Nested scope
subs = sync.subscriptions
subs.add("github:pr-opened")
subs.remove(sub_id)

# Spawn a child with delegated capabilities
child = tasks.create(
    name="reindex",
    mode="one_shot",
    code=memory.read("prompts/reindex").id,
    content="Reindex after data-sync failure",
)
```

### Variable Table

The executor maintains a variable table during each run:

```python
VariableTable = dict[str, ScopeEntry]

@dataclass
class ScopeEntry:
    type: str                           # e.g. "Memory", "Task"
    context: dict                       # instance state (IDs, etc.)
    methods: list[ToolSpec]             # available methods
    children: dict[str, ScopeEntry]     # nested attributes
```

### Tool Return Contract

Every tool handler returns a `ToolResult`:

```python
@dataclass
class ToolResult:
    content: Any                # return value shown to agent
    scope: dict | null          # variables to add to scope
    release: list[str] | null   # variables to remove from scope
```

Scope lifecycle:
- Created when a tool returns `scope` entries.
- Released explicitly via `release`, or auto-cleaned at end of run.
- Nested scopes cascade-release with their parent.

### Proxy Generation from Output Schema

A tool's `output_schema` drives proxy generation. Example:

```json
{
  "type": "object",
  "properties": {
    "content": {"type": "string"},
    "id": {"type": "string", "format": "uuid"}
  },
  "methods": {
    "update": {"handler": "brain.tools.memory.update", "args": {"content": "string"}},
    "versions": {"handler": "brain.tools.memory.versions", "args": {}}
  }
}
```

The executor reads `methods` from the schema, constructs a proxy class, binds
the handler calls with the instance `context` (the memory ID), and injects
the proxy into the variable table.

## Runner Implementations

### Lambda Runner

Our executor controls the full conversation loop.

1. Receive task ID + event ID (if subscription-triggered).
2. Load task from DB.
3. Load prompt from `Memory[task.code]` (resolve includes).
4. Build system prompt via ContextEngine (tool instructions from TaskTool).
5. Build user message: `task.content` + event payload.
6. Inject `search_tools` and `run_code` as Bedrock tool definitions.
7. Claude conversation loop (max N turns):
   - LLM returns tool_use for `search_tools` or `run_code`.
   - Execute in sandbox with proxy objects.
   - Return results to LLM.
   - Loop until stop_reason != tool_use.
8. Record Run (tokens, cost, duration, result, scope_log).
9. Validate result against `task.return_schema` if set.
10. Daemon -> WAITING. One-shot -> COMPLETED.
11. On failure: increment retry_count, backoff or DISABLED.

### ECS Runner

Claude Code CLI runs in a container. Our tools are exposed as an MCP server.

1. Launch ECS task.
2. MCP server starts in the container, reads task's TaskTool entries.
3. Exposes `search_tools` and `run_code` as MCP tools.
4. Claude Code CLI starts with:
   - System prompt / CLAUDE.md from `Memory[task.code]`.
   - Initial message from `task.content` + event payload.
   - MCP server connected.
5. Claude Code uses `run_code` for cogent system interaction (memory, tasks,
   events) and its native tools (bash, files, git) for everything else.
6. On session end, record Run.
7. If `clear_context=false`, session state persists to S3 for resumption.

### Sandbox Component

The sandbox is a shared library used by both runners:

```
src/brain/sandbox/
    executor.py     # variable table, scope management, code execution
    proxy.py        # proxy object generation from tool output_schema
    server.py       # MCP server wrapping search_tools + run_code (for ECS)
```

- Lambda: `executor.py` called directly by the Lambda handler.
- ECS: `server.py` wraps executor as an MCP server alongside Claude Code.

## Scheduler

The scheduler is itself a daemon task. Its prompt calls scheduler tools.

### Scheduler Flow (per tick)

Triggered by `scheduler:tick` cron event.

1. **Match events.** Query unmatched events. For each, find subscriptions with
   matching `event_pattern` (enabled only). Create `EventDelivery` rows
   (status=pending). Mark WAITING daemons with pending deliveries as RUNNABLE.

2. **Age priorities.** Compute effective priority for each RUNNABLE task:
   `effective_priority = task.priority + f(now - task.runnable_since)`.
   Prevents starvation of low-priority tasks.

3. **Check resources.** For each RUNNABLE task, verify all required resources
   have capacity. Tasks that fail the check -> BLOCKED.

4. **Unblock.** Check BLOCKED tasks. If resources are now available -> RUNNABLE.

5. **Select.** Softmax sample from eligible RUNNABLE tasks by effective
   priority. Sample up to available execution slots.

6. **Dispatch.** For each selected task, call `dispatch_task(task_id)` which
   invokes the appropriate runner (Lambda or ECS).

### Scheduler Tools

The scheduler task uses these tools (themselves entries in the Tool table):

```
match_events()          match pending events to subscriptions
select_tasks()          softmax sample from runnable tasks
dispatch_task(task_id)  send to executor
check_resources()       query resource availability
unblock_tasks()         move BLOCKED -> RUNNABLE where possible
kill_task(task_id)      force-terminate a running task (SIGKILL)
```

## What Gets Eliminated

### Tables

| Removed | Replaced By |
|---|---|
| Program | Memory entries |
| Trigger | Subscription on Task |

### Code

| Removed | Reason |
|---|---|
| `src/mind/program.py` | Programs are memory entries |
| `src/mind/bootstrap_loader.py` | No programs to bootstrap |
| `src/brain/lambdas/dispatcher/` | No EventBridge; scheduler matches in DB |
| `execute_python_program()` in executor | All execution is prompt-based |
| `eggs/ovo/programs/` | Prompts migrate to memory |
| `src/dashboard/routers/programs.py` | No program entity |
| Trigger CLI commands and router | Replaced by subscription CLI/router |

### Infrastructure

| Removed | Reason |
|---|---|
| EventBridge rules and targets | Events matched in DB by scheduler |
| Dispatcher Lambda | Scheduler tool handles event matching |
| Separate sandbox Lambda | Sandbox is a library, not a deployment |

## Source Structure

```
src/
  brain/
    db/
      models/
        __init__.py             re-exports all models
        task.py                 Task
        task_tool.py            TaskTool
        subscription.py         Subscription
        memory.py               Memory, MemoryVersion
        tool.py                 Tool
        event.py                Event
        event_delivery.py       EventDelivery
        run.py                  Run
        resource.py             Resource, ResourceUsage
        cron.py                 Cron
        conversation.py         Conversation
        channel.py              Channel
        alert.py                Alert
        budget.py               Budget
        trace.py                Trace
      repository.py
    lambdas/
      executor/
        handler.py              Lambda executor entry point
    sandbox/
      executor.py               variable table, scope management
      proxy.py                  proxy object generation
      server.py                 MCP server for ECS runner
  memory/
    store.py
    context_engine.py
    cli.py
  mind/
    cli.py                      task, subscription, memory, tool, event,
                                resource, cron commands
    task_loader.py
    tool_loader.py
    memory_loader.py
  dashboard/
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
  run/
    cli.py                      ECS task interaction (list, shell)
  cli/
    __main__.py
```

## Open Questions

1. **Subscription pattern syntax.** Simple glob (`task:completed:*`) or
   something richer (regex, JSONPath on payload)?
2. **Scope serialization.** If an ECS session is resumed, should the variable
   table be persisted and restored? Or start fresh each wake?
3. **Tool versioning.** Tools will evolve. Should TaskTool pin a tool version
   or always use latest?
4. **Resource join table.** Should `resources: list[UUID]` on Task become a
   `TaskResource` join table with `amount` (for tasks needing 2 units of a
   pool resource)?
