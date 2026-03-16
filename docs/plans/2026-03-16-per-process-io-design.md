# Per-Process IO Channels Design

Every CogOS process gets its own stdin/stdout/stderr channels, enabling process-level I/O routing, parent-child stdio communication, and shell attachment to specific processes.

## Channel Naming

Extends the existing `process:<name>` implicit channel convention:

- `process:<name>:stdin` — input to the process
- `process:<name>:stdout` — program output
- `process:<name>:stderr` — commentary, errors, diagnostics

## Channel Creation

Created eagerly by `procs.spawn()` alongside existing spawn channels. Three `ChannelType.NAMED` channels per process.

## Process TTY Flag

```python
class Process(BaseModel):
    ...
    tty: bool = False  # forward stdio to global io channels
```

When `tty=True`, writes to `process:<name>:stdout/stderr` are also forwarded to global `io:stdout/io:stderr`. Shell-spawned processes (`llm`, `spawn --tty`) get `tty=True`. Background daemons default to `tty=False`.

## `me` Capability

```python
me.stdout("hello world")           # → process:<name>:stdout (+io:stdout if tty)
me.stderr("retrying...")           # → process:<name>:stderr (+io:stderr if tty)
msg = me.stdin()                   # ← next message from process:<name>:stdin
```

## ProcessHandle (Parent Access)

```python
p = procs.spawn("worker", content="do stuff")
p.stdin("here's your input")      # write to process:worker:stdin
output = p.stdout()                # read from process:worker:stdout
errors = p.stderr()                # read from process:worker:stderr

# Existing structured IPC unchanged
p.send({"type": "config", ...})
msg = p.recv()
```

## Executor Wiring

Helper replaces direct `io:*` publishing:

```python
def _publish_process_io(repo, process, stream: str, text: str) -> None:
    _publish_io(repo, process, f"process:{process.name}:{stream}", text)
    if process.tty:
        _publish_io(repo, process, f"io:{stream}", text)
```

- `run_code` stdout → `_publish_process_io(repo, process, "stdout", result)`
- Final assistant text → `_publish_process_io(repo, process, "stderr", text)`
- Exceptions → `_publish_process_io(repo, process, "stderr", error)`

## Shell Commands

### `attach`

```
attach scheduler              # read-only: tail stdout+stderr
attach -i scheduler           # interactive: also forward stdin
```

Ctrl+c detaches. Output prefixed with channel (stdout green, stderr red).

### `spawn --tty`

```
spawn worker --content "do stuff" --tty
```

### `ps` TTY column

```
NAME                     STATUS       MODE       RUNNER   TTY    PRI
scheduler                running      daemon     lambda         100.0
shell-1710612345         running      one_shot   local    *       0.0
```

### `llm`

Sets `tty=True` on temp process. TTY forwarding pushes output to global `io:*`, shell drains as before.

## Global IO Channels

`io:stdin/stdout/stderr` remain as the "terminal" — the aggregation point for TTY-attached processes. The shell drains these. No change to existing behavior.

## Migration

- Add `tty BOOLEAN DEFAULT FALSE` to `cogos_process` table
- Existing processes get `tty=False` (correct for background daemons)
- No data migration needed
- Global `io:*` channels unchanged
- Existing spawn channels unchanged
