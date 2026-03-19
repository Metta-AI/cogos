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

Returns `ProcessHandle` — the universal interface for process interaction.

## spawn(name, content?, capabilities?, ...)

```python
# Simple child process
child = procs.spawn("subtask-42", content="Process items 420-429")

# With capabilities (NOT inherited — must pass explicitly)
child = procs.spawn("worker", content="Do the thing", capabilities={
    "channels": channels.scope(names=["metrics*"]),
    "workspace": dir.scope("/workspace/", ops=["read"]),
    "email_ops": email.scope(to=["ops@company.com"]),
})

# With model override and schema for spawn channel
child = procs.spawn("quick-task", content="Classify this",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    schema={"result": "string", "score": "number"},
    capabilities={"channels": channels.scope(names=["metrics*"])})
```

Parameters:
- `name` (required) — unique process name
- `content` — prompt/instructions for the child
- `schema` — schema for the spawn channel (inline dict or named schema)
- `capabilities` — dict of grant_name → capability instance (or None for unscoped lookup)
- `priority` — scheduling priority (default 0.0)
- `runner` — "lambda" or "ecs" (default "lambda")
- `model` — model override

Returns `ProcessHandle`.

## Process Handles

Spawning or looking up a process returns a ProcessHandle — the universal interface for process interaction.

```python
# Spawn returns a handle
child = procs.spawn("worker", content="process this data",
    schema={"result": "string", "score": "number"},
    capabilities={"channels": channels.scope(names=["metrics*"])}
)

# Send to child via spawn channel
child.send({"task": "analyze", "data": [1, 2, 3]})

# Read child's responses
msgs = child.recv(limit=5)

# Check status
print(child.status())  # "running", "completed", etc.

# Kill a child process
child.kill()

# Wait for child to complete (event-driven, ends current run)
child.wait()
```

### Coordination

```python
h1 = procs.spawn("task_a", content="...", capabilities={...})
h2 = procs.spawn("task_b", content="...", capabilities={...})

# Wait for first child to complete
Process.wait_any([h1, h2])

# Wait for all children to complete
Process.wait_all([h1, h2])
```

### Looking up processes

```python
handle = procs.get(name="worker")
handle = procs.get(id="<uuid>")

# Same interface: send, recv, kill, status, wait
print(handle.status())
```

## Scoping

```python
# Read-only process inspection (no spawn)
readonly_procs = procs.scope(ops=["list", "get"])

# Spawn only (no list/get)
spawn_only = procs.scope(ops=["spawn"])
```
