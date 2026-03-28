# Coglet Architecture

*Fractal asynchronous control for distributed agent systems.*

## 1. Primitive

**Coglet** = **COG** (control) + **LET** (execution)

- **COG** — slow, reflective, supervises and adapts LETs
- **LET** — fast, reactive, executes tasks

Recursive composition: a COG is itself a LET under a higher COG. The system forms a temporal hierarchy where layers share a uniform interface and differ only in cadence and scope.

The boundary between COG and LET is an interface contract, not a deployment topology. They may share a process, span processes, or run on different machines — the protocol is the same.


## 2. LET Interface

**LET** = Listen, Enact, Transmit

Event-driven. The framework owns the channels and dispatches to the Coglet.

| Method | Caller | Purpose |
|---|---|---|
| `on_message(channel, event)` | framework | Handle an incoming event on a named channel |
| `on_enact(command)` | COG (via framework) | Apply a control plane directive — fire-and-forget |
| `transmit(channel, result)` | self | Push output to a named channel |

`on_message` is the data plane. `on_enact` is the control plane. `transmit` is the only outbound call.


## 3. COG Interface

**COG** = Create, Observe, Guide

A COG supervises one or more LETs. The 1:1 case (one COG paired with one LET) is the common default. Fleet management is a natural extension, not a prerequisite.

| Method | Purpose |
|---|---|
| `observe(let_id, channel) → AsyncStream[Result]` | Subscribe to a named channel on a LET's transmit stream |
| `guide(let_id, command)` | Send a command to a LET's `on_enact` — fire-and-forget |
| `create(config) → CogletHandle` | Spawn a new LET, return its handle |

The COG's only feedback loop is observe. `guide` has no return value — the COG knows its command took effect by watching subsequent transmissions.

A COG is itself a LET under a higher COG. Its `on_message` receives the results it observes. Its `on_enact` receives directives from above. The recursion bottoms out at a LET with no COG (standalone reactive process) or a COG with no parent (root supervisor).

## 4. Capabilities

Capabilities are injected infrastructure, orthogonal to COG/LET. Any Coglet may be granted any capability at construction time.

### 4.1 Memory

```python
class Memory(Protocol):
    async def store(self, key: str, value: Any) -> None: ...
    async def retrieve(self, key: str) -> Any: ...
    async def query(self, predicate: Callable) -> List[Any]: ...
```

Backend is a deployment decision. A Coglet without memory is a valid, stateless Coglet.

## 5. Communication Model

COG and LET communicate via asynchronous channels with clear boundaries — neither can see inside the other except via the agreed protocol.

Properties:
- Location-agnostic
- Backpressure-tolerant
- Naturally distributable
- No synchronous calls — guide is fire-and-forget, observe is the only feedback path

## 6. Mixins

Optional mixins for any Coglet.

### 6.1 LifeLet

Lifecycle hooks. All no-ops by default.

| Hook | When | Use |
|---|---|---|
| `on_start()` | Channels open | Connect resources, announce presence |
| `on_stop()` | Shutdown signal | Flush state, release resources |

A hook that raises aborts the transition.

Child lifecycle (start, stop, health) is observed through the CogletHandle returned by `create()`, not through hooks on the parent.

### 6.2 GitLet

The repo *is* the policy. The Coglet executes from HEAD and accepts patches as commits.

`on_enact` for a GitLet means pull + reload. Rollback is `git revert`. Branching enables parallel policy experiments. No custom serialization — the patch protocol is just git.

### 6.3 LogLet

Adds a log stream separate from transmit. The COG subscribes to it independently.

- **transmit stream** — results, actions, decisions
- **log stream** — traces, state snapshots, metrics

The COG controls log verbosity via `guide`. Without LogLet, the COG only sees the transmit stream.

### 6.4 TickLet

Adds time-driven behavior via a periodic `on_tick(elapsed)` callback. Tick rate is configurable and adjustable at runtime via `on_enact`.

Useful for COGs that need to periodically observe their fleet and decide on interventions, or for LETs that need heartbeats, polling, or scheduled maintenance. Without TickLet, a Coglet is purely reactive to incoming events.

### 6.5 MulLet

Manages N identical LETs as a single logical unit. The parent COG sees one CogletHandle.

| Method | Purpose |
|---|---|
| `create(n, config) → CogletHandle` | Spawn N copies of the same LET config |
| `map(event) → List[(let_id, event)]` | Route an incoming event to one or more children |
| `reduce(results) → Result` | Aggregate child outputs into one transmission |

Distribution policies (round-robin, broadcast, hash) are configured via `map`. The parent COG observes one reduced stream and guides one unit — the fan-out is internal.
