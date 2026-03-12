# Channels Design

Replace free-form text events with explicit, typed channels. Every process gets its own channel. Spawning creates private parent↔child channels. Named topic channels support broader pub/sub.

## Channel Model

A **Channel** is a typed, append-only message stream with a defined schema and an owner.

Three ways channels get created:

1. **Implicit process channel** — every process automatically gets a channel named `process:<name>`. The process can publish to it. Closes when the process completes/is disabled.

2. **Spawn channels** — spawning a child creates two private unidirectional channels:
   - `spawn:<parent_id>→<child_id>` (parent-to-child)
   - `spawn:<child_id>→<parent_id>` (child-to-parent)

3. **Explicit named channels** — `channels.create("metrics", schema="metrics")`. Owned by the creating process. Outlive the creator by default unless `auto_close=True`.

All channels have a schema. Spawn and implicit channels use a built-in `message` schema (`{"body": "string", "data": "dict"}`) unless overridden. Messages are validated on send.

## Schemas

Declarative Pydantic-like DSL stored as `.md` files in CogOS file storage:

```yaml
# /schemas/metrics.schema.md
fields:
  value: number
  label: string
  tags: list[string]
  metadata: dict
```

Nested schemas via sub-schema fields:

```yaml
# /schemas/position.schema.md
fields:
  x: number
  y: number

# /schemas/agent_state.schema.md
fields:
  name: string
  pos: position
  targets: list[position]
```

Inline schemas at spawn/channel creation time:

```python
child = procs.spawn("worker", content="...",
    schema={"result": "string", "score": "number"},
    capabilities={...}
)

ch = channels.create("alerts", schema={"severity": "string", "msg": "string"})
```

Inline sub-schemas:

```python
procs.spawn("worker",
    schema={
        "result": "string",
        "location": {"x": "number", "y": "number"},
        "items": "list[{name: string, count: number}]",
    },
    ...
)
```

**Supported types:** `string`, `number`, `bool`, `list`, `list[T]`, `dict`, `dict[K,V]`, and references to other schema names.

**Schema capability:**
- `schemas.get("metrics")` — load a schema from CogOS files
- `schemas.list()` — list available schemas

**Channel introspection:**
- `channel.schema()` — returns the schema definition

## Process Handle

The universal interface for interacting with any process. Obtained via spawn or lookup.

```python
# Spawning
child = procs.spawn("worker", content="...", capabilities={...})

# Lookup
handle = procs.get(id="<uuid>")
handle = procs.get(name="worker")
```

**Operations:**

| Method | Description |
|---|---|
| `handle.send(msg)` | Send on parent→child channel. Validated against schema. |
| `handle.recv(limit=10)` | Read from child→parent channel. |
| `handle.kill()` | Shut down the process (sets status to disabled). |
| `handle.status()` | Current process status. |
| `handle.wait()` | Event-driven wait. Current run ends, parent re-wakes when child completes. |
| `handle.channel` | The child→parent channel object (for subscriptions or direct reads). |
| `handle.schema()` | Schema for this process's channels. |

**Coordination primitives:**

```python
h1 = procs.spawn("task_a", ...)
h2 = procs.spawn("task_b", ...)

Process.wait_any([h1, h2])   # re-wake when first child completes
Process.wait_all([h1, h2])   # re-wake when all children complete
```

**Lookup handles** (`procs.get()`) give the same interface. If the caller has a parent↔child relationship, send/recv use the private spawn channels. Otherwise, the caller gets access to the process's named topic channel (read via subscription or pull) but no private send channel.

## Named Topic Channels

```python
# Create
ch = channels.create("metrics", schema="metrics")
ch = channels.create("alerts", schema={"severity": "string", "msg": "string"})

# Publish
ch.send({"severity": "high", "msg": "disk full"})

# Consume — pull
msgs = ch.read(limit=10)

# Consume — push (handler-based wakeup)
ch.subscribe()

# Discovery
channels.list()
ch = channels.get("metrics")
ch.schema()

# Lifecycle
ch.close()
```

**Ownership:** the creating process owns the channel and can write to it. Others need an explicit capability grant to publish. Read access is granted separately.

## Capabilities

**New capabilities:**

| Name | Purpose | Scopable by |
|---|---|---|
| **channels** | Create/list/get/close named channels | ops (create/list/get/close), name patterns |
| **schemas** | Load/list schema definitions | name patterns |

**Modified capabilities:**

- **procs** — `spawn()` returns a Process handle, accepts optional `schema=`. `get()` returns a Process handle. New static: `Process.wait_any()`, `Process.wait_all()`.

**Delegation rules for channels:**

Same narrowing rules as all capabilities. Child scope must be equal or narrower than parent scope:

```python
procs.spawn("reader", capabilities={
    "metrics_feed": ch.scope(ops=["read"]),
})
```

**Replaces:**

- `events.emit()` → `channel.send()` on process topic or named channel
- `events.query()` → `channel.read()` or `channels.get().read()`
- `Handler.event_pattern` → `Handler.channel` FK
- `EventsCapability` → deprecated, replaced by channels

## Data Model

**New tables:**

```sql
cogos_channel (
    id UUID PK,
    name TEXT NOT NULL,
    owner_process UUID FK → cogos_process,
    schema_id UUID FK → cogos_schema (nullable),
    inline_schema JSONB (nullable),
    channel_type TEXT NOT NULL,  -- 'implicit', 'spawn', 'named'
    auto_close BOOLEAN DEFAULT FALSE,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
)

cogos_channel_message (
    id UUID PK,
    channel UUID FK → cogos_channel,
    sender_process UUID FK → cogos_process,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ
)

cogos_schema (
    id UUID PK,
    name TEXT NOT NULL,
    definition JSONB NOT NULL,
    file_id UUID FK → cogos_file (nullable),
    created_at TIMESTAMPTZ
)
```

**Modified tables:**

- `cogos_handler` — replace `event_pattern TEXT` with `channel UUID FK → cogos_channel`
- `cogos_process` — add `schema_id UUID FK → cogos_schema` (optional, for implicit channel schema). Deprecate `output_events`.

**Dropped tables:**

- `cogos_event`
- `cogos_event_delivery`
- `cogos_event_outbox`
- `cogos_event_type`

Clean cut — no dual-write migration. Drop old tables, create new ones, migrate all processes and handlers to channels.

## External I/O Integration

I/O bridges write to well-known channels instead of emitting events.

| Bridge | Channel | Schema file |
|---|---|---|
| Discord | `io:discord:<channel_name>` | `images/cogent-v1/files/cogos/io/discord/schema.md` |
| Email | `io:email:inbound` | `images/cogent-v1/files/cogos/io/email/schema.md` |
| Cron | Target process implicit channel or named channel | built-in `message` schema |
| System lifecycle | `system:lifecycle` | built-in lifecycle schema |

Schema `.md` files live alongside their bridge code in the image spec and are registered as `cogos_schema` rows during image apply.

## Ingress Changes

The current ingress flow (event → outbox → delivery → wake process) becomes:

1. Message written to channel → `cogos_channel_message` row
2. Handlers bound to that channel are matched
3. Processes with matching handlers are set to RUNNABLE
4. Scheduler dispatches as before

The outbox pattern may still be useful for reliable delivery of channel messages to handlers — same claim/process/done lifecycle, but keyed on channel messages instead of events.

## Dashboard Updates

- Replace event log views with channel message views
- Add channel list/detail pages (owner, schema, message count, subscribers)
- Update process detail to show bound channels (implicit + spawn + subscribed)
- Add schema browser
- Update handler views to show channel bindings instead of event patterns
