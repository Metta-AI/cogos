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
- **Requester**: Has a context that needs a program. Sends context descriptions to Authors. The Requester is typically the level above the Author — the entity that owns the environment the child will run in. A Virtual Universe requests Cogs from a Cogent. A Cogent requests Coglets from a Cog. The Requester may also be the Author itself (self-commissioning). The Requester provides the interaction capabilities (the environment-side tools the child will need).
- **Runtime**: Trusted substrate that executes program templates. Attaches capabilities it was given and runs the process. Has no authority of its own — it mechanically binds what the Author and Requester provide. The Runtime owns the child's execution lifecycle — start, pause, resume, kill. In CogOS, the Runtime is the dispatcher/executor infrastructure.

### Commissioning Phase

1. Requester sends a **Context** to the Author:
   - `body`: byte string — describes the situation the child will run in
   - `type`: byte string — what kind of thing the body is
   - `source_id`: UUID — who is asking
2. Author responds with a **ProgramTemplate**:
   - `program`: byte string — the code/instructions for the child
   - `capability_spec`: list of capability requirements (type, name, config)
3. The Author provides **cognitive capabilities** — tools for the child to think and plan (memory, internal scratch space, reflection prompts). The Requester provides **interaction capabilities** — tools for the child to observe and act in the environment (file access, API calls, domain-specific sensors and actuators). For example: a Cog authoring a Coglet for a code review Episode would provide cognitive capabilities (memory of past reviews, the review policy) while the Episode provides interaction capabilities (read access to the diff, ability to post comments).
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
- **`execute()`**: Run an arbitrary program in the child's space and get back what changed. "Change this and tell me what happened." The program runs as the Author (using the supervisor capability), not as the child — the Author is inspecting and modifying the child's space from outside.

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

The Requester specifies the supervision mode at commissioning time (it owns the environment and knows whether streaming is possible). The Runtime configures the channel accordingly:

- Fire-and-forget: log channel created, no supervisor capability instantiated, memory state returned on completion
- Streaming: log channel created with real-time delivery, supervisor capability instantiated and provided to Author, memory state returned on completion

The child's program is identical in both modes.

### Termination

A child process terminates when:

1. **Self-termination**: The child's program completes (returns or exits)
2. **Runtime termination**: The Runtime kills the process (timeout via `max_duration_ms`, resource limits, or runtime shutdown)
3. **Author termination** (streaming only): The Author uses `execute()` to halt the child's program

In all cases, the Runtime is responsible for collecting the final memory state and delivering it (along with any buffered logs) to the Author. If the child crashes, the Runtime delivers whatever memory state and logs are available, plus an error indication.

The protocol does not prescribe retry or error recovery — that is the Author's policy. The Author receives the result (success or failure) and decides whether to commission a new child, patch the template, or do nothing.

### Memory State Return

On termination, the Runtime serializes the child's memory state — the contents of all memory capabilities bound to the child process — and posts it to the Author's log channel as a completion message. This is a snapshot of the child's versioned memory at the moment of termination.

In CogOS terms: the Runtime reads all `memory_version` rows associated with the child's memory capabilities, serializes them, and writes a `Completion(logs, memory_state, status)` message to the parent-child channel. The Author's Handler receives this like any other channel message.

### Relationship to Existing CogOS Primitives

- **ProgramTemplate.capability_spec** is a declarative manifest. At instantiation, each spec entry is resolved to a concrete `process_capability` row bound to the new child Process. The spec is the request; `process_capability` is the binding.
- **SupervisorCapability** is a new capability type. It implements `_narrow()` by restricting which child process IDs can be supervised — an Author can only supervise children it authored. `_check()` verifies the target process ID is in scope. `search()` and `execute()` are its public methods. Delegation is possible: an Author could grant a narrower SupervisorCapability to a child, enabling supervision of grandchildren.
- **`log()` uses the existing child-to-parent Channel** (the `spawn:responses` pattern in ProcsCapability). The authoring protocol does not replace bidirectional spawn channels — it uses the existing child-to-parent channel for logs.

## Key Invariants

1. **`log()` is universal**: Every level calls `log()`. The child never knows its supervision mode.
2. **The Author is not the operator**: The Runtime owns execution lifecycle (start, pause, resume, kill). The Author produces the program and observes/patches.
3. **Capabilities come from Author + environment, not Runtime**: The Runtime attaches what it's given. Cognitive tools come from the Author. Interaction tools come from the environment.
4. **The protocol is fractal**: The same commissioning → supervision → learning loop applies at every level of the hierarchy.
5. **Learning is opaque**: The protocol defines how observations flow (logs up, patches down) but not how the Author processes them.
6. **Scope can only narrow**: When capabilities are delegated from Author to child, `_narrow()` ensures the child cannot gain wider access than the Author holds.
