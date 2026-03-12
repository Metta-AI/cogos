# Events

Events are the communication backbone of CogOS. They form an append-only log that processes use to signal state changes, request work, and coordinate.

## Event structure

```
id              UUID        unique identifier
event_type      str         hierarchical type (e.g. "task:completed")
source          str         who emitted it (e.g. "process:discord-handle-message")
payload         dict        arbitrary JSON data
parent_event    UUID?       causal link to a prior event
created_at      datetime    immutable timestamp
```

## Event types

Types use `:` separators by convention:

```
process:run:success       process completed a run
process:run:failed        process run failed
discord:dm                direct message received
discord:mention           bot mentioned in a channel
email:received            inbound email
system:tick:minute        scheduler heartbeat
approval:requested        process needs human sign-off
```

## Emitting events

```python
events.emit("task:completed", {
    "task_name": "data-sync",
    "records_processed": 1500,
})

# Causal chaining
events.emit("task:followup", {"action": "notify"}, parent_event=original_event_id)
```

## Querying events

```python
recent = events.query("email:received", limit=10)
for e in recent:
    print(e.event_type, e.payload)

# All events (unscoped only)
all_recent = events.query(limit=50)
```

## Handlers

Handlers bind processes to event patterns. When a matching event arrives, the scheduler marks the process RUNNABLE.

A daemon process with `handlers=["discord:dm", "discord:mention"]` will wake whenever either event type appears.

When the process runs, the triggering event is injected into its user message:

```
Event: discord:dm
Payload: {
  "content": "Hello!",
  "author": "daveey",
  "author_id": "123456789"
}
```

## Human-in-the-loop

Events enable human interaction without special mechanisms:

1. Process emits `approval:requested` with action details
2. Process registers a handler for `approval:granted:{process_name}`
3. Process returns, goes to WAITING
4. Human approves via dashboard or Discord
5. Approval event wakes the process

## Event scoping

The events capability can be scoped on emit and query patterns:

```python
# Can only emit task:* events
scoped = events.scope(emit=["task:*"])

# Can only query email:* events
scoped = events.scope(query=["email:*"])
```

When query is scoped, you must provide an event_type — unfiltered queries are denied.

## Immutability

Events are append-only. Once emitted, they cannot be modified or deleted. This guarantees a complete audit trail of everything that happened in the system.
