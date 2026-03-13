# Authoring Protocol Design Spec

## Overview

This spec defines the core parent-child protocol used at every level of the CogOS hierarchy. The protocol governs how a parent process (an **Author**) produces programs for child processes, supervises their execution, and learns from their results. The same protocol applies at every level — Human authoring Cogents, Cogent authoring Cogs, Cog authoring Coglets — making it fractal.

The protocol is embedded in CogOS primitives (Processes, Capabilities, Channels) with the abstract protocol described as a framing layer.

## The Hierarchy

| Level | Authors | Authored by | Cognitive tools come from | Interaction tools come from |
|-------|---------|-------------|--------------------------|----------------------------|
| **Human** | Cogents | Society | Evolution | Physical Universe |
| **Cogent** | Cogs | Human | Human | Virtual Universe |
| **Cog** | Coglets | Cogent | Cogent | Environments |
| **Coglet** | Actions | Cog | Cog | Episodes |

Each level except the leaf has two jobs:

1. **Author**: Make, optimize, and monitor the level below
2. **Reflect**: Learn from the results of authoring

Coglets are the leaf — they just execute their policy and call `log()`.

CogOS implements the levels below Human. The Human-Cogent boundary is the same protocol — the Human reviews logs, patches policy, searches the Cogent's space.

## Abstract Protocol

### Roles

Three roles participate:

- **Author**: Produces program templates in response to contexts. Learns from returned logs and memory. At different hierarchy levels this is a Human, Cogent, or Cog.
- **Requester**: Has a context that needs a program. Sends context descriptions to Authors.
- **Runtime**: Trusted substrate that executes program templates. Attaches capabilities it was given and runs the process. Has no authority of its own — it mechanically binds what the Author and Requester provide.

### Commissioning Phase

1. Requester sends a **Context** to the Author:
   - `body`: byte string — describes the situation the child will run in
   - `type`: byte string — what kind of thing the body is
   - `source_id`: UUID — who is asking
2. Author responds with a **ProgramTemplate**:
   - `program`: byte string — the code/instructions for the child
   - `capability_spec`: list of capability requirements (type, name, config)
3. The Author provides **cognitive capabilities** (memory, reflection, planning tools). The Requester or environment provides **interaction capabilities** (sensors, actuators, domain tools).
4. The Runtime receives the template, the concrete capabilities, and an identity. It mechanically creates the process, attaches the capabilities, and starts execution.

### Supervision Phase

Two modes, invisible to the child:

#### Fire-and-Forget

The child runs, calls `log(msg)` which buffers. On termination, the Runtime returns to the Author:
- All buffered logs
- The child's final memory state

#### Streaming

The child runs, calls `log(msg)` which streams to the Author in real-time. The Author retains a **tendril** — a supervisor connection to the child's space:

- **`search()`**: Discover what files, processes, and capabilities exist in the child's space. "What's going on in there?"
- **`execute()`**: Run an arbitrary program in the child's space and get back what changed. "Change this and tell me what happened."

The child does not participate in search or execute — these operate on the child's space, not through the child. The child just runs its policy and calls `log()`.

On termination, the final memory state is still returned to the Author.

In both modes, the child calls `log()` identically. It does not know whether it is streaming or fire-and-forget.

### Learning Loop

The protocol defines interfaces for learning but not the mechanism. At each non-leaf level:

1. **Commission**: Receive context, produce program template
2. **Observe**: Receive logs (streaming or batch) plus final memory state
3. **Reflect**: Process observations — opaque, the Author decides how
4. **Patch**: Update the program template for next time, or `execute()` on a running child to patch it live

The protocol guarantees:
- Logs always flow up via `log()`
- Final memory state always returns on completion
- In streaming mode, `search()` and `execute()` are always available
- The Author is free to ignore logs, never patch, or patch constantly — that's the Author's policy, not the protocol

## CogOS Mapping

### Program Templates

A `ProgramTemplate` is a new CogOS entity:

```
ProgramTemplate:
    id: UUID
    author_id: UUID          -- the Process that produced this template
    program: bytes           -- the program code/instructions
    capability_spec: [       -- declarative manifest of what the child needs
        {
            capability: str  -- capability type name (e.g., "memory", "files")
            name: str        -- alias for the child to use
            config: dict     -- requested scoping
        }
    ]
    created_at: timestamp
```

The capability spec is a manifest — "this program needs a memory capability scoped to X and a files capability scoped to Y." The actual capability instances come from the Author (cognitive tools) and the environment (interaction tools).

### Instantiation

When the Runtime instantiates a template, it receives:

```
Instantiation:
    template: ProgramTemplate
    capabilities: [              -- concrete instances from Author + environment
        {
            name: str            -- matches a name in the capability_spec
            instance: Capability -- actual capability object
        }
    ]
    identity: UUID
```

The Runtime:
1. Creates a new Process with the template's program code
2. Binds each provided capability instance by name as `process_capability` rows
3. Assigns the identity
4. Creates the supervision channel(s) back to the Author
5. Starts the process

The Runtime does not grant capabilities — it attaches capabilities it was given. It is trusted infrastructure.

### Supervision in CogOS

**`log(msg)`**: The child writes to a Channel with a Handler bound to the Author's Process. In fire-and-forget mode, messages buffer in the channel. In streaming mode, the Handler delivers messages to the Author in real-time.

**`search()` and `execute()`**: The Author holds a supervisor capability over the child's space. This is not a message the child receives — it operates on the child's environment from outside.

- `search()` enumerates files, processes, and capabilities available in the child's space
- `execute()` runs an arbitrary program in the child's space and returns the result

These map to a new `SupervisorCapability` in CogOS, scoped to a specific child process.

### Mode Selection

The Author or Requester specifies the supervision mode at commissioning time. The Runtime configures the channel accordingly:

- Fire-and-forget: log channel created, no supervisor capability instantiated, memory state returned on completion
- Streaming: log channel created with real-time delivery, supervisor capability instantiated and provided to Author, memory state returned on completion

The child's program is identical in both modes.

## Key Invariants

1. **`log()` is universal**: Every level calls `log()`. The child never knows its supervision mode.
2. **The Author is not the operator**: The Runtime owns execution lifecycle (start, pause, resume, kill). The Author produces the program and observes/patches.
3. **Capabilities come from Author + environment, not Runtime**: The Runtime attaches what it's given. Cognitive tools come from the Author. Interaction tools come from the environment.
4. **The protocol is fractal**: The same commissioning → supervision → learning loop applies at every level of the hierarchy.
5. **Learning is opaque**: The protocol defines how observations flow (logs up, patches down) but not how the Author processes them.
6. **Scope can only narrow**: When capabilities are delegated from Author to child, `_narrow()` ensures the child cannot gain wider access than the Author holds.
