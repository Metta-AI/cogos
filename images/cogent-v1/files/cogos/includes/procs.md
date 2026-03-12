# Procs API

Process management — list, inspect, and spawn processes.

## list(status?, limit?)

```python
# All processes
for p in procs.list():
    print(f"{p.name}: {p.status} (priority={p.priority})")

# Filter by status
running = procs.list(status="running")
waiting = procs.list(status="waiting")
```

Returns `list[ProcessSummary]` — id, name, mode, status, priority, runner, parent_process.

## get(name?, id?)

```python
p = procs.get(name="scheduler")
print(p.name, p.status, p.model, p.content)

p = procs.get(id="some-uuid")
```

Returns `ProcessDetail` — includes content, code, model, retry info, timestamps.

## spawn(name, content?, capabilities?, ...)

```python
# Simple child process
child = procs.spawn("subtask-42", content="Process items 420-429")

# With capabilities (NOT inherited — must pass explicitly)
child = procs.spawn("worker", content="Do the thing", capabilities={
    "events": events,                                       # pass as-is
    "workspace": dir.scope("/workspace/", ops=["read"]),    # narrowed
    "email_ops": email.scope(to=["ops@company.com"]),       # scoped email
})

# With model override
child = procs.spawn("quick-task", content="Classify this",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    capabilities={"events": events})
```

Parameters:
- `name` (required) — unique process name
- `content` — prompt/instructions for the child
- `capabilities` — dict of grant_name → capability instance (or None for unscoped lookup)
- `priority` — scheduling priority (default 0.0)
- `runner` — "lambda" or "ecs" (default "lambda")
- `model` — model override

Returns `SpawnResult` — id, name, status, parent_process.

## Scoping

```python
# Read-only process inspection (no spawn)
readonly_procs = procs.scope(ops=["list", "get"])

# Spawn only (no list/get)
spawn_only = procs.scope(ops=["spawn"])
```
