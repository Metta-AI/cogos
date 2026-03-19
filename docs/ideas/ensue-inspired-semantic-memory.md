# Ensue-Inspired Semantic Memory for CogOS

Source: https://ensue.dev/docs/core-concepts/

Ensue is a semantic memory network for AI agents. It stores memories with vector embeddings, organizes them into hypergraph clusters, and lets agents search by meaning rather than exact keys. Core primitives: Store, Search (semantic + hypergraph), Share (access control), Automate (subscriptions), Invites (cross-org).

## What CogOS Already Has (Overlap)

- **Events** — append-only signal log with causal chains (`parent_event`) — similar to Ensue's event subscriptions
- **Files** — hierarchical key-value store (`cogos/includes/`, context engine) — similar to Ensue's namespaced memory
- **Capabilities** — scoped, per-process access control — similar to Ensue's access policies
- **Channels** — inter-process messaging — similar to Ensue's subscriptions

## Ideas

### 1. Semantic Search over Files/Events (High Value, Low Risk)

CogOS files use key-based lookup. The `search` tool does keyword matching on capabilities. Adding vector embeddings to the File and Event models would let processes ask "what do we know about authentication?" instead of needing exact paths.

- Add an `embedding` column to the `file` table
- Generate embeddings on write via Bedrock Titan
- Add a `semantic_search(query)` method to the `files` capability that does cosine similarity over pgvector
- Recommended starting point — additive change, uses existing infra (Bedrock, PostgreSQL)

### 2. Hypergraph / Causal Discovery

CogOS events already have `parent_event` for causal chains. Ensue takes this further with automatic cluster detection — discovering which processes/files/events are semantically related even without explicit links. This could power a dashboard view showing "impact radius" of a change.

- Build a periodic process that computes semantic similarity between recent events and surfaces clusters
- Visualize in the dashboard Events tab

### 3. Subscriptions with Semantic Matching

CogOS handlers currently match events by `event_type` (exact string). Ensue lets agents subscribe to semantic patterns — "anything related to deployment failures."

- Extend `Handler` model with an optional `match_query` (text) + `match_embedding` (vector)
- The dispatcher checks both exact type match and cosine similarity
- Processes could register interest in topics, not just event type strings

### 4. Scoped Memory Namespaces

Ensue uses `/`-delimited paths (`project/acme/decisions`) with namespace-level access control. CogOS files already use hierarchical keys, but access control is per-capability-binding, not per-namespace.

- Extend the `files` capability's `_narrow()` logic to support `read_prefixes` and `write_prefixes` in the scope config
- Allows "process X can read `shared/` but only write to `project/alpha/`"

### 5. Cross-Agent Memory Sharing

Today each cogent is isolated (own DB). Ensue's invites/sharing model lets agents from different orgs share specific memory namespaces.

- A shared polis-level file store (or dedicated "shared memory" table in the polis DB) with per-cogent read/write grants
- Cogent Alpha publishes findings that cogent Beta can query

### 6. Minor Ideas

- **Description-based vs value-based embedding** — choose whether to embed the file's description or its content. Useful when content changes frequently but "what this file is about" stays stable.
- **Reactive file watching** — "watch this file namespace and re-run when anything changes" pattern for daemon processes, beyond what cron + event handlers provide today.
