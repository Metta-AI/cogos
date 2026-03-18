# Tournament Submission Cogent Design

**Goal:** Support tournament submissions where the uploaded artifact is thin, while the real policy logic runs in the live cogent.

**Architecture:** The submitted artifact is a `MultiAgentPolicy` proxy with a hardcoded cogent endpoint. On `PreparePolicy`, the proxy calls the cogent's bootstrap endpoint, which starts an episode-scoped policy host and returns a websocket URL. The proxy connects and forwards `BatchStep` calls over that connection. The tournament runner sees a normal policy and requires no changes.

**Tech Stack:** CogOS app/process model, ECS/Fargate, websocket policy transport, episode-scoped auth tokens, stable ingress routing

---

## Problem

Our current tournament submission mental model is still too bundle-first: package a policy snapshot, upload it, and run that frozen artifact locally in the tournament environment.

That targets the wrong thing for live cogents like `dr.alpha`.

What we actually want is a **tournament submission cogent design** where:
- the submitted artifact is minimal
- the live cogent remains the source of policy behavior
- tournament episodes can spin up temporary policy hosts backed by the live cogent
- the runner connects over the existing websocket policy protocol

Today, that boundary is not modeled explicitly in CogOS.

## Non-Goals

- replacing the tournament policy websocket protocol
- running live LLM inference directly on every `BatchStep`
- treating the tournament policy host as infrastructure outside the app/process model
- forcing tournament submission to be a snapshot of the cogent rather than the live cogent itself
- requiring changes to the tournament runner or policy protocol

## Submitted Artifact: The Proxy Policy

The tournament submission is a `MultiAgentPolicy` implementation that acts as a thin proxy to the live cogent. From the tournament runner's perspective, it is a normal policy. Internally, it handles all bootstrap and connection logic.

The proxy has a hardcoded endpoint for the live cogent (e.g., `https://cogent.example.com/bootstrap`).

On `PreparePolicy`:
1. Calls the cogent's bootstrap endpoint with episode context
2. Receives back `ws_url`, auth token, episode id, and lease TTL
3. Opens a websocket connection to the episode host

On `BatchStep`:
- Forwards the request to the episode host over the websocket connection
- Returns the response to the tournament runner

On teardown / episode end:
- Closes the websocket connection cleanly

This design means the tournament runner needs no changes. It loads a `MultiAgentPolicy`, calls `PreparePolicy`, calls `BatchStep` — the proxy handles everything else.

## The Bootstrap Endpoint

The cogent exposes a bootstrap endpoint that the proxy policy calls during `PreparePolicy`.

The bootstrap endpoint:
- receives an episode bootstrap request from the proxy
- derives episode metadata and auth
- starts an episode-scoped policy host (see below)
- waits for the host to signal readiness
- returns the websocket endpoint, auth token, episode id, and lease TTL

This should be a standard app-defined CogOS process — a normal short-lived process, not a special out-of-band control plane.

## The Episode Host

The episode host is what sits on the other side of the websocket connection returned by bootstrap. It serves the existing `PreparePolicy` / `BatchStep` websocket protocol for one episode, backed by the live cogent's actual policy logic.

### Why ECS, not Lambda

- The tournament transport expects a long-lived websocket server for the duration of the episode
- Lambda would imply a different architecture: API Gateway websocket, per-message invocations, externalized connection state
- ECS matches the desired lifecycle directly: serve one episode, then die

### Lifecycle

1. Bootstrap process starts an ECS task for the episode host
2. Episode host initializes, loads policy state from the cogent
3. Episode host registers readiness (signals back to bootstrap)
4. Episode host serves `PreparePolicy` / `BatchStep` over websocket
5. Episode host exits on: episode completion, client disconnect, failure, or lease expiry

### Stable front door

The bootstrap endpoint should return a routed endpoint such as `wss://.../episodes/<token>` rather than a raw task IP.

This keeps TLS, auth, routing, and task replacement under CogOS control instead of leaking task networking details to the proxy.

## CogOS Modeling Options

### Option A: New process mode

Add a new process mode such as `service` or `persistent`.

Pros:
- explicit lifecycle semantics
- clearer separation from one-shot ECS execution
- easier to reason about readiness and health

Cons:
- larger scheduler/runtime surface change

### Option B: Leased ECS runner

Keep `runner="ecs"`, but add lease and heartbeat semantics so a process can remain alive for the duration of an episode.

Pros:
- smaller surface area
- reuses existing ECS substrate

Cons:
- risks overloading the current one-shot `ecs` meaning
- still needs service-like concepts: readiness, heartbeat, endpoint registration, expiry

### Recommended direction

Use the same Fargate substrate, but model the episode host explicitly as a leased or persistent process rather than pretending it is just a normal one-shot ECS run with a longer timeout.

## App-Level Ownership

This should remain part of app space, for example under an app like `apps/cvc`.

That app can own:
- the proxy policy code (the submitted artifact)
- the bootstrap endpoint / process
- the episode host process definition
- policy state and model weights
- channels for readiness, logs, and lifecycle events
- slower adaptation and analysis processes outside the hot path

## Full Lifecycle

1. Tournament runner loads the submitted `MultiAgentPolicy` proxy.
2. Tournament runner calls `PreparePolicy` on the proxy.
3. Proxy calls the live cogent's bootstrap endpoint.
4. A short-lived CogOS process handles bootstrap: starts an episode host, waits for readiness.
5. Bootstrap returns `ws_url`, auth token, episode id, lease TTL to the proxy.
6. Proxy opens websocket to the episode host.
7. Tournament runner calls `BatchStep` on the proxy; proxy forwards over websocket.
8. Episode host exits on episode completion, disconnect, failure, or lease expiry.

## Open Questions

- What policy state does the episode host need, and how does it get it? (Model weights, cached embeddings, episode history — loaded from S3? Streamed from the cogent?)
- What does the bootstrap endpoint's request schema look like? (Episode id, map, opponent info, any tournament metadata?)
- Does the episode host need to call back to the cogent during the episode (e.g., for slow reasoning or adaptation), or does it run autonomously once bootstrapped?
- How does the cogent manage concurrent episodes? (Multiple episode hosts running simultaneously, resource limits, queueing?)

## Acceptance Criteria

- The submitted tournament artifact is a `MultiAgentPolicy` proxy that requires no tournament-side changes
- The proxy can call a bootstrap endpoint on the live cogent and receive a ready websocket endpoint
- The episode host serves the existing websocket policy protocol for one episode
- The episode host is cleaned up on disconnect, completion, failure, or TTL expiry
- The design stays inside app/process space and preserves capability scoping
- The design clearly supports the intended use case: submit a thin tournament policy while the real policy logic runs in the live cogent
