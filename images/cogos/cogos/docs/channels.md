# Channels

Channels are the communication backbone of CogOS. They are typed, append-only message streams that processes use to exchange data, signal state changes, request work, and coordinate. Channels replace the older event system with structured, schema-validated messaging.

## Message structure

```
id              UUID        unique identifier
channel         str         channel name (e.g. "alerts", "process:worker")
source          str         who sent it (e.g. "process:scheduler")
payload         dict        message data, validated against the channel's schema
created_at      datetime    immutable timestamp
```

## Channel types

### Implicit channels (`process:<name>`)

Every process automatically gets an implicit channel named `process:<name>`. Processes publish their status and results here. Other processes can read or subscribe to these channels to monitor progress.

```python
# A process named "worker" automatically has channel "process:worker"
# Other processes can read it:
msgs = channels.read("process:worker", limit=5)
```

### Spawn channels (`spawn:<parent_id>→<child_id>`)

When a process spawns a child, a private bidirectional channel is created between them. The ProcessHandle returned by `procs.spawn()` wraps this channel, providing `send()` and `recv()` methods for direct parent-child communication.

```python
child = procs.spawn("analyzer", content="analyze this data",
    schema={"result": "string", "score": "number"})

# Parent sends to child via the spawn channel
child.send({"task": "analyze", "data": [1, 2, 3]})

# Parent reads child's responses
msgs = child.recv(limit=5)
```

### Named channels

Named channels are explicitly created for pub/sub messaging. Any process with the appropriate capability can create, send to, read from, or subscribe to named channels.

```python
# Create a channel with an inline schema
ch = channels.create("alerts", schema={"severity": "string", "msg": "string"})

# Create with a named schema (references a .schema.md file)
ch = channels.create("metrics", schema="metrics")
```

## Sending messages

Messages are validated against the channel's schema before being accepted. Invalid messages are rejected.

```python
# Send a message
channels.send("alerts", {"severity": "high", "msg": "disk full"})

# Schema violations raise an error
channels.send("alerts", {"bad_field": 123})  # error: payload doesn't match schema
```

## Reading messages

Pull-based reading retrieves messages from a channel.

```python
msgs = channels.read("alerts", limit=10)
for m in msgs:
    print(m.source, m.payload, m.created_at)
```

## Subscriptions (push-based)

Subscribing to a channel tells the scheduler to wake your process when new messages arrive. This is the event-driven model — your process goes to WAITING and is marked RUNNABLE when a subscribed channel has new messages.

```python
# Subscribe to a channel
channels.subscribe("alerts")

# When woken, the triggering message is injected into your prompt
```

This replaces the old handler mechanism. Instead of registering handlers for event types, processes subscribe to channels.

## Schemas

Every channel has a schema that defines the structure of its messages. Schemas can be:

- **Inline dicts** — specified at channel creation time
- **Named schemas** — reference `.schema.md` files stored in the file system

```python
# Inline schema
channels.create("alerts", schema={"severity": "string", "msg": "string"})

# Named schema
channels.create("metrics", schema="metrics")

# Inspect a channel's schema
channels.schema("metrics")

# List and get schemas
schemas.list()
s = schemas.get("metrics")
print(s.definition)
```

## Integration with process handles

The ProcessHandle returned by `procs.spawn()` and `procs.get()` wraps spawn channel operations (`send`, `recv`, `status`, `wait`, `kill`). See the procs API for process handle details.

## Human-in-the-loop

Channels enable human interaction without special mechanisms:

1. Process sends an approval request to a named channel (e.g. `approvals`)
2. Process subscribes to a response channel (e.g. `approvals:granted:<process_name>`)
3. Process returns, goes to WAITING
4. Human approves via dashboard or Discord
5. Approval message on the response channel wakes the process

## Channel scoping

The channels capability can be scoped by operations (`ops`) and channel name patterns (`names`). Patterns use fnmatch syntax (`*` matches anything, `?` matches one char). See the channels include for the scoping API.

## Immutability

Channels are append-only. Once a message is sent, it cannot be modified or deleted. This guarantees a complete audit trail of all communication in the system.
