# Child Completion Notification

## Problem

When the supervisor spawns a helper, it's fire-and-forget. The helper can silently die — the supervisor never knows and never retries. The helper's content includes voluntary error reporting (`channels.send("supervisor:help", ...)`), but if the helper crashes before reaching that code, nothing happens.

More broadly, any parent that spawns children has no reliable way to learn the outcome. `handle.wait()` exists as an API but the executor never interprets the return value. `handle.status()` requires the parent to poll. There is no push-based notification on success.

Failure notification partially exists: `_notify_parent_on_failure` sends a `child:failed` message on the spawn channel. But nothing wakes the parent to read it, no equivalent exists for success, and the message type splits success/failure into separate events rather than using a unified signal with an exit code.

## How operating systems solve this

In Unix, the kernel makes it impossible to silently lose a child:

1. **SIGCHLD**: when a child exits (success or failure), the kernel sends SIGCHLD to the parent. The parent doesn't have to poll — notification is automatic.
2. **wait()**: the parent can block until a child exits and receive its exit status.
3. **Zombies**: if the parent ignores both, the dead child stays in the process table as a zombie until the parent acknowledges it. The OS forces the parent to deal with it.

The key insight: the OS doesn't give the parent a way to *inspect* children. It *pushes* results to the parent. The relationship is kernel-managed and notification is automatic.

## Proposed solution: automatic child completion notification

Apply the SIGCHLD pattern to CogOS. When a child completes (success or failure), CogOS automatically notifies the parent via the spawn channel and wakes it.

### Change 1: Notify parent on child exit (success and failure)

The executor already calls `_notify_parent_on_failure` in the error path. Replace this with a unified `_notify_parent_on_exit` that fires on both success and failure, with an exit code — mirroring Unix where SIGCHLD fires regardless of how the child exited and `wait()` returns the status.

```python
# On spawn:{child_id}→{parent_id}
{
    "type": "child:exited",
    "exit_code": 0,           # 0 = success, 1 = failure, 2 = timeout, 3 = throttled
    "process_name": "helper-task",
    "process_id": "...",
    "run_id": "...",
    "duration_ms": 4500,
    "error": null,            # non-null on failure
    "result": { ... },        # from run.result, if any (null on failure)
}
```

Exit codes:
- `0` — completed successfully
- `1` — failed (error in `error` field)
- `2` — timed out
- `3` — throttled (Bedrock rate limit)
- `4` — disabled (max retries exceeded)

### Change 2: Auto-register parent for spawn channel wakeup

Currently, `procs.spawn()` creates bidirectional spawn channels but no Handler for the parent. Without a Handler, the dispatcher's `match_messages()` won't create deliveries and won't wake the parent.

In `procs.spawn()`, after creating the recv channel (`spawn:{child}→{parent}`), also create a Handler mapping that channel to the parent process. This means child completion messages automatically create deliveries and wake the parent daemon — exactly like SIGCHLD.

For one-shot parents (which will be COMPLETED by the time the child finishes), the delivery just sits there harmlessly.

### Change 3: Add `handle.runs()` to ProcessHandle

So the parent can inspect child run history when it wakes:

```python
h = procs.get(name="helper-task")
runs = h.runs(limit=3)
# -> [RunInfo(status="failed", error="timeout", duration_ms=900000, ...)]
```

This exposes the existing `repo.list_runs(process_id=...)` data through the handle. Fields: status, error, duration_ms, tokens_in, tokens_out, cost_usd, result, created_at, completed_at.

## What this means for the supervisor

Today the supervisor wakes only on `supervisor:help` messages. With these changes, it will also wake on spawn channel messages when helpers exit. The message payload has `"type": "child:exited"` with an `exit_code`, so the supervisor can distinguish these from help requests and branch on the outcome.

The supervisor image needs a new section for handling child exit notifications:
- `exit_code == 0`: success — log it, optionally notify Discord
- `exit_code != 0`: failure — check the error, decide whether to re-spawn or escalate to human

This eliminates the need for helpers to self-report failure — the OS (CogOS) handles it.

## What this does NOT include

- **Blocking `wait()`**: deferred. Useful for ECS-runner supervisors that want synchronous child execution, but a bigger change (executor needs to interpret the wait spec, poll in the sandbox, handle Lambda timeouts). The notification pattern covers the daemon supervisor case without it.
- **A general inspection capability**: deferred. `handle.runs()` on ProcessHandle covers the immediate need. A broader `inspect` capability with scope narrowing is a separate effort for system-level observability.
- **Zombie semantics**: not needed. Unlike Unix where PIDs are a scarce resource, CogOS processes in the DB are cheap. The notification is sufficient without forcing acknowledgment.

## Files to change

1. `src/cogos/executor/handler.py` — replace `_notify_parent_on_failure` with `_notify_parent_on_exit`, call it in both success and failure paths
2. `src/cogos/capabilities/procs.py` — in `spawn()`, create Handler for parent on recv channel
3. `src/cogos/capabilities/process_handle.py` — add `runs()` method returning run history
4. `images/cogent-v1/apps/supervisor/supervisor.md` — add child notification handling section
