# Channels

Channels are typed, append-only message streams for inter-process communication. Every message is validated against the channel's schema.

## Channel Types

- **Implicit** (`process:<name>`) — every process gets one automatically for publishing status and results
- **Spawn** (`spawn:<id>→<id>`) — private bidirectional channels created when spawning child processes
- **Named** — explicitly created for pub/sub topics (e.g. `io:discord:dm`, `metrics`)

## Operations

```python
# Create a channel with inline schema
ch = channels.create("alerts", schema={"severity": "string", "msg": "string"})

# Create with a named schema
ch = channels.create("metrics", schema="metrics")

# Send — validated against schema
channels.send("alerts", {"severity": "high", "msg": "disk full"})

# Read messages
msgs = channels.read("alerts", limit=10)
for m in msgs:
    print(m.payload)

# Subscribe for push notifications (scheduler wakes you on new messages)
channels.subscribe("alerts")

# List and inspect
channels.list()
info = channels.get("metrics")
channels.schema("metrics")  # get schema definition

# Close a channel you own
channels.close("alerts")
```

## Schemas

Schemas define the message structure. Defined as `.schema.md` files or inline dicts.

```python
# Get a schema
s = schemas.get("metrics")
print(s.definition)

# List all schemas
schemas.list()
```

## Scoping

```python
# Restrict to specific operations
channels.scope(ops=["read", "subscribe"])

# Restrict to specific channel names
channels.scope(names=["metrics*", "io:discord:*"])
```
