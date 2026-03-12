# Events API

Append-only event log for inter-process communication.

## emit(event_type, payload?, parent_event?)

```python
# Simple event
events.emit("task:completed", {"task_name": "data-sync"})

# With causal chaining
events.emit("task:followup", {"action": "notify"}, parent_event=original_id)

# No payload
events.emit("heartbeat:alive")
```

Returns `EmitResult` with id, event_type, created_at.

## query(event_type?, limit?)

```python
# Query by type
recent = events.query("email:received", limit=10)
for e in recent:
    print(e.event_type, e.source, e.payload)

# All recent events (only if unscoped)
all_events = events.query(limit=50)
```

Returns `list[EventRecord]` — each has id, event_type, source, payload, parent_event, created_at.

## Scoping

```python
# Restrict emit to task events only
task_events = events.scope(emit=["task:*"])

# Restrict query to email events only
email_events = events.scope(query=["email:*"])

# Both
scoped = events.scope(emit=["task:*"], query=["email:*", "task:*"])
```

Patterns use fnmatch syntax (`*` matches anything, `?` matches one char).

When query is scoped, you must provide an event_type — unfiltered queries are denied.

## Common event types

```
process:run:success     process completed
process:run:failed      process failed
discord:dm              direct message received
discord:mention         bot mentioned
email:received          inbound email
system:tick:minute      scheduler heartbeat
approval:requested      needs human sign-off
```
