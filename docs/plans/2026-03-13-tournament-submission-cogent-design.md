# Tournament Submission Cogent Design

**Goal:** Support tournament submissions where the uploaded artifact is thin, while the real policy logic runs in the live cogent.

**Architecture:** Add an explicit bootstrap step ahead of the policy websocket connection. Bootstrap is a normal short-lived CogOS process that starts an episode-scoped remote policy host, waits for readiness, and returns a websocket endpoint. The episode host serves the existing tournament `PreparePolicy` / `BatchStep` websocket protocol for one episode, then exits on completion, disconnect, or lease expiry.

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

Relevant constraints:
- the tournament policy protocol already uses websocket for `PreparePolicy` and `BatchStep`
- `PreparePolicyResponse` is empty, so endpoint negotiation cannot happen inside the policy protocol
- the websocket client needs the URL before it sends `PreparePolicy`
- the current `ecs` runner is one-shot: dispatch a task, execute a run, and exit
- an episode-scoped live policy host needs readiness, endpoint registration, health, and teardown semantics

## Non-Goals

- replacing the tournament policy websocket protocol
- running live LLM inference directly on every `BatchStep`
- treating the tournament policy host as infrastructure outside the app/process model
- forcing tournament submission to be a snapshot of the cogent rather than the live cogent itself

## Proposed Shape

### 1. Bootstrap before websocket connect

The tournament runner, or a thin submitted proxy, should perform a bootstrap call before opening the policy websocket.

Bootstrap returns:
- `ws_url`
- auth token or signed path
- episode id
- lease expiry or TTL

This keeps endpoint discovery outside `policy.proto`, which matches the current protocol shape.

### 2. Bootstrap is a normal short-lived CogOS process

Bootstrap should be a standard app-defined process, not a special out-of-band control plane.

Responsibilities:
- receive episode bootstrap request
- derive episode metadata and auth
- start the episode host
- wait for readiness
- return the websocket endpoint

### 3. Episode host is ECS, not Lambda

The episode host should be an ECS task, not Lambda.

Reasoning:
- the current tournament transport expects a long-lived websocket server for the duration of the episode
- Lambda would imply a different architecture entirely: API Gateway websocket, per-message Lambda invocations, and externalized connection state
- ECS matches the desired lifecycle directly: serve one episode, then die

### 4. Prefer a stable front door

Bootstrap should ideally return a routed endpoint such as `wss://.../episodes/<token>` rather than a raw task IP.

This keeps:
- TLS
- auth
- routing
- task replacement

under CogOS control instead of leaking task networking details to the tournament side.

### 5. Keep this app-defined

This should remain part of app space, for example under an app like `apps/cvc`.

That app can own:
- policy code
- policy state
- bootstrap process
- episode-host process definition
- channels for readiness, logs, and lifecycle events
- slower adaptation and analysis processes outside the hot path

## Lifecycle

1. Tournament runner builds episode setup context.
2. Bootstrap request is sent to the live cogent.
3. A short-lived CogOS process handles bootstrap.
4. Bootstrap starts an episode-scoped policy host.
5. Policy host registers readiness and endpoint.
6. Bootstrap returns the websocket endpoint.
7. Tournament runner connects and uses normal `PreparePolicy` / `BatchStep`.
8. Policy host exits on episode completion, disconnect, failure, or lease expiry.

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

Keep `runner=\"ecs\"`, but add lease and heartbeat semantics so a process can remain alive for the duration of an episode.

Pros:
- smaller surface area
- reuses existing ECS substrate

Cons:
- risks overloading the current one-shot `ecs` meaning
- still needs service-like concepts: readiness, heartbeat, endpoint registration, expiry

## Recommended Direction

Use the same Fargate substrate, but model the episode host explicitly as a leased or persistent process rather than pretending it is just a normal one-shot ECS run with a longer timeout.

In practice that means:
- bootstrap remains a normal short-lived process
- episode host is a long-lived-but-temporary process with readiness and TTL
- endpoint discovery happens before the websocket connection
- the live cogent remains the owner of the real policy behavior

## Dependencies Outside This Repo

The tournament side likely needs a first-class bootstrap seam ahead of websocket connection.

Important current constraints in `m1`:
- the websocket client connects before `PreparePolicy`
- `PreparePolicyResponse` cannot carry endpoint negotiation
- bundle-loaded `MultiAgentPolicy` construction does not currently receive the full prepare request

That means the clean solution is to add an explicit bootstrap hook in the tournament runner, not to hide endpoint negotiation inside the policy protocol.

## Acceptance Criteria

- CogOS has a clear design for tournament submission backed by a live cogent
- a short-lived bootstrap process can start an episode host and return a ready websocket endpoint
- the episode host serves the existing websocket policy protocol for one episode
- the episode host is cleaned up on disconnect, completion, failure, or TTL expiry
- the design stays inside app/process space and preserves capability scoping
- the design clearly supports the intended use case: submit a thin tournament policy while the real policy logic runs in the live cogent
