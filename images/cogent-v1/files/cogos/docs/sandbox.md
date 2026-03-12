# CogOS Sandbox

The sandbox is the execution environment for process code. It mediates all interaction between LLM-generated Python and the outside world through capability proxy objects.

## Execution Model

Processes interact with the system through two meta-capabilities:

- **search(query)** — discover available capabilities by keyword
- **run_code(code)** — execute Python in the sandbox

Inside `run_code`, capability objects are pre-injected as top-level variables. The LLM writes natural Python against them:

```python
config = files.read("/config/system")
print(config.content)

events.emit("task:completed", {"result": "success"})

child = procs.spawn("worker", content="do the thing", capabilities={
    "workspace": dir.scope("/workspace/", ops=["list", "read"]),
})
```

## Capability-Only Authority

**No ambient capabilities.** A process only gets the capabilities explicitly bound to it via ProcessCapability records. If a process doesn't have a `files` binding, it can't access files. If it doesn't have `events`, it can't emit or query events.

Capabilities are injected by grant name — a process can hold multiple grants of the same capability type with different scopes:

```
email_me       → email scoped to ["daveey@gmail.com"]
email_team     → email scoped to ["team@company.com"]
workspace      → dir scoped to "/workspace/"
audit_log      → file_version scoped to "/logs/audit", ops=["add"]
```

## Capability Scoping

Every capability supports `.scope()` which returns a narrowed copy. Scoping is monotonic — you can only restrict, never widen.

```python
# Start with full dir access
workspace = dir.scope("/workspace/")

# Narrow to read-only
readonly = workspace.scope(ops=["list", "read"])

# Narrow further to a subdirectory
docs = readonly.scope(prefix="/workspace/docs/")

# This would fail — cannot widen prefix
workspace.scope(prefix="/")  # ValueError
```

Every public method on a capability calls `_check()` before executing. If the operation or target is outside the scope, it raises `PermissionError`.

## Spawn and Delegation

When a process spawns a child via `procs.spawn()`, capabilities are NOT inherited. The parent must explicitly pass them:

```python
procs.spawn("worker", capabilities={
    "events": events,                                    # pass as-is
    "workspace": dir.scope("/workspace/", ops=["read"]), # narrowed
})
```

Delegation rules:
- Parent must hold the capability type it's delegating
- Child scope must be equal to or narrower than parent scope
- A scoped parent cannot delegate an unscoped grant (that would widen)

## Sandbox Restrictions

The sandbox runs with a restricted set of Python builtins. The following are **blocked**:

- `import` / `__import__` — no module imports
- `open` — no filesystem access
- `exec` / `eval` — no nested code execution
- `getattr` / `hasattr` — no reflection on capability internals
- `compile` / `globals` / `locals` — no namespace introspection

Available builtins: `print`, `len`, `range`, `enumerate`, `zip`, `sorted`, `min`, `max`, `sum`, `str`, `int`, `float`, `list`, `dict`, `set`, `tuple`, `bool`, `isinstance`, `map`, `filter`, `any`, `all`, `abs`, `round`, `reversed`, `repr`, plus `json` for serialization and standard exception types.

Capability internal state (like `_scope`) is protected by a descriptor that raises `AttributeError` when accessed from sandbox code. This prevents LLM-generated code from inspecting its own permissions.

## Discovery

Use the `capabilities` directory object to discover what's available:

```python
capabilities.list()              # names with one-line descriptions
capabilities.count()             # total count
capabilities.search("email")     # search by keyword

discord.help()                   # full method signatures and schemas
```

## Event Scoping

The events capability supports scoping on both emit and query:

```python
# Can only emit task events, can query anything
events.scope(emit=["task:*"])

# Can only query email events
events.scope(query=["email:*"])

# When query is scoped, event_type is required (no unfiltered queries)
events.query()  # PermissionError if query patterns are set
```

## Built-in Capabilities

| Name | Purpose | Scopable by |
|---|---|---|
| **file** | Single-file access | key, ops (read/write/delete/get_metadata) |
| **file_version** | Version history access | key, ops (add/list/get/update) |
| **dir** | Directory-prefix access | prefix, ops (list/read/write/create/delete) |
| **events** | Event log | emit patterns, query patterns |
| **procs** | Process management | ops (list/get/spawn) |
| **secrets** | Secret retrieval | key patterns |
| **discord** | Discord messaging | channels, ops (send/react/create_thread/dm/receive) |
| **email** | Email via SES | recipients (to), ops (send/receive) |
| **me** | Scoped scratch/tmp/log | — (scoped by process/run automatically) |
| **resources** | Resource pool queries | — |
| **scheduler** | Scheduler operations | — (scheduler process only) |
