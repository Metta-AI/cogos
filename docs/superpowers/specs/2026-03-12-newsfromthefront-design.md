# newsfromthefront — Design Spec

**Date:** 2026-03-12
**Status:** Approved

---

## Overview

`newsfromthefront` is a CogOS application that continuously monitors the competitive landscape for a given project. It ingests a GitHub repository plus user-written context, runs daily web research via the Perplexity API, tracks findings over time, and delivers delta reports to a Discord channel as threaded posts. Users refine the research brief by replying to report threads. A backfill capability allows historical analysis to seed the knowledge base before daily incremental operation begins.

---

## Architecture

### Image

A new CogOS image: `newsfromthefront`, added as processes within the existing `cogent-v1` image. All process names are prefixed `newsfromthefront-` to provide ad-hoc namespacing within the flat image structure.

### Processes

| Process | Mode | Runner | Trigger |
|---|---|---|---|
| `newsfromthefront-researcher` | daemon | lambda | daily cron channel message |
| `newsfromthefront-analyst` | daemon | lambda | `newsfromthefront:findings-ready`, `newsfromthefront:discord-feedback` |
| `newsfromthefront-test` | daemon | lambda | `newsfromthefront:run-requested` (mode: "test") |
| `newsfromthefront-backfill` | daemon | ecs | `newsfromthefront:run-requested` (mode: "backfill") |

`newsfromthefront-backfill` uses the ECS runner because iterating over a wide date range may exceed Lambda's execution timeout.

### New Capability

`web_search` — a first-class CogOS capability backed by the Perplexity API. Registered in `BUILTIN_CAPABILITIES` and reusable by any future cogent.

### Channels

| Channel | Producer | Consumer | Purpose |
|---|---|---|---|
| `newsfromthefront:findings-ready` | researcher, test | analyst | Signals that raw findings are ready for analysis |
| `newsfromthefront:discord-feedback` | discord-handle-message | analyst | Routes Discord thread replies back to the analyst |
| `newsfromthefront:run-requested` | discord-handle-message | test, backfill | Triggers on-demand runs |

### File Store Layout

```
newsfromthefront/
  brief.md                  — GitHub URL + user goals/context (evolves via thread replies)
  knowledge-base.json       — structured history of all findings seen to date
  state.json                — Discord thread IDs for active report threads
  findings/<date>.md        — raw Perplexity output per researcher run
  reports/<date>.md         — generated analyst report per run
```

---

## Processes

### `newsfromthefront-researcher`

**Trigger:** Daily cron channel message.

**Behavior:**
1. Read `newsfromthefront/brief.md` — GitHub URL, user goals, accumulated context, known competitors list.
2. Fetch the repo's README and key documentation files via the GitHub REST API (using `secrets.get("cogent/github_token")`).
3. Derive a set of Perplexity search queries from the project description — the LLM generates these from the brief, not a hardcoded list, so query quality improves as the brief grows richer. Use `recency: "day"` to focus on fresh content.
4. Run each query via the `web_search` capability.
5. Write all raw findings to `newsfromthefront/findings/<date>.md`.
6. Send `{run_id, findings_key, date, is_test: false, is_backfill: false}` on `newsfromthefront:findings-ready`.

**Capabilities:** `web_search`, `dir`, `channels`, `secrets`

**Retry:** `max_retries=3, retry_backoff_ms=60000`. On GitHub API unavailability, falls back to the cached project description in `brief.md` and proceeds with search only.

---

### `newsfromthefront-analyst`

**Trigger:** `newsfromthefront:findings-ready` or `newsfromthefront:discord-feedback`.

**On `findings-ready`:**
1. Read the findings file at `findings_key`.
2. Read `newsfromthefront/knowledge-base.json`.
3. Identify genuinely new findings — deduplicate by URL and title against the knowledge base.
4. Classify new findings by type: `competitor`, `product_update`, `funding`, `launch`, `other`.
5. Write the delta report to `newsfromthefront/reports/<date>.md`.
6. If `is_test: false` and `is_backfill: false`: post the report to the configured Discord channel as a new thread titled "Newsfromthefront — `<date>`". Store the thread ID in `newsfromthefront/state.json`.
7. If `is_backfill: true`: skip Discord posting, update knowledge base only. The `newsfromthefront-backfill` process drives these analyst invocations sequentially (emit one `findings-ready` message, wait for the analyst to complete via the spawn channel, then proceed to the next interval) to avoid concurrent writes to `knowledge-base.json`. When all intervals are complete, backfill posts a single summary thread.
8. If `is_test: true`: post to a clearly labeled test thread. Do not update the knowledge base or state.
9. Update `newsfromthefront/knowledge-base.json` with new findings (unless `is_test: true`).

**On `discord-feedback`:**
1. Read the feedback content and author.
2. Read `newsfromthefront/brief.md`.
3. Incorporate the feedback — update goals, add context, refine competitors list, adjust search focus.
4. Write the updated brief back to `newsfromthefront/brief.md`.
5. Reply in the Discord thread to confirm: "Brief updated." so the user knows their feedback was received.

**Capabilities:** `web_search`, `dir`, `channels`, `discord`, `secrets`

**Error handling:** If Discord posting fails after retries, post a brief error note to the channel so failures are never silent.

---

### `newsfromthefront-test`

**Trigger:** `newsfromthefront:run-requested` with `mode: "test"`.

**Behavior:** Runs the full researcher + analyst loop from scratch. Passes `is_test: true` throughout — does not update the knowledge base or state. Posts report to a clearly labeled test thread (title: "Newsfromthefront TEST — `<date>`"). Intended for tuning runs where the user wants to see end-to-end output without affecting production state.

**Capabilities:** `web_search`, `dir`, `channels`, `discord`, `secrets`

---

### `newsfromthefront-backfill`

**Trigger:** `newsfromthefront:run-requested` with `mode: "backfill"`, `after_date`, `before_date`.

**Behavior:**
1. Parse the date range. Determine granularity — week-by-week for ranges > 30 days, day-by-day otherwise.
2. For each interval: run researcher-style Perplexity searches using `after_date`/`before_date` params. Write findings to `newsfromthefront/findings/<date>.md`. Emit on `newsfromthefront:findings-ready` with `is_backfill: true`.
3. After all intervals complete: post a summary thread to Discord — "Backfill complete: `<after_date>` → `<before_date>`. Knowledge base initialized with N findings."

**Runner:** ECS (long-running; Lambda timeout not suitable for wide date ranges).

**Capabilities:** `web_search`, `dir`, `channels`, `discord`, `secrets`

---

## `web_search` Capability

### Location

`src/cogos/capabilities/web_search.py` — registered in `BUILTIN_CAPABILITIES`.

### Schema

```
web_search.search(
  query:       string   — the search query
  recency:     string?  — "day" | "week" | "month" (relative window, for normal runs)
  after_date:  string?  — ISO date, lower bound (for backfill)
  before_date: string?  — ISO date, upper bound (for backfill)
) → {
  summary: string,
  sources: list[{title: string, url: string, snippet: string}]
}
```

### Implementation

Calls Perplexity's `/chat/completions` endpoint with `model: "sonar"`. Reads API key from `secrets.get("cogent/perplexity_api_key")`. Maps `recency` to Perplexity's `search_recency_filter` param; maps `after_date`/`before_date` to Perplexity's date filter params.

Default scoping: unrestricted. Future scoping may restrict to allowed query patterns.

---

## Channel Schemas

### `newsfromthefront:findings-ready`

```yaml
fields:
  run_id:       string
  findings_key: string
  date:         string
  is_test:      bool
  is_backfill:  bool
```

### `newsfromthefront:discord-feedback`

```yaml
fields:
  thread_id: string
  content:   string
  author:    string
```

### `newsfromthefront:run-requested`

```yaml
fields:
  mode:        string   — "test" | "backfill"
  after_date:  string?
  before_date: string?
```

---

## Knowledge Base Structure

`newsfromthefront/knowledge-base.json`:

```json
{
  "findings": [
    {
      "id": "<uuid>",
      "date": "2026-03-12",
      "type": "competitor | product_update | funding | launch | other",
      "title": "...",
      "summary": "...",
      "url": "...",
      "relevance": "brief note on why this matters to the project"
    }
  ],
  "competitors": ["..."],
  "last_run": "2026-03-12"
}
```

The `competitors` list is fed back into the researcher's search query generation on each run, so coverage deepens automatically over time. Deduplication uses URL and title — if a finding has been seen before it is not reported as new.

---

## Discord Feedback Loop

When a user @mentions the bot in a report thread:

1. The Discord bridge captures the mention via `io:discord:mention`. The message payload includes `channel_id` (the Discord thread's channel ID) — this is already supported by the bridge.
2. `discord-handle-message` checks whether `channel_id` is present in `newsfromthefront/state.json`.
3. If yes: forwards to `newsfromthefront:discord-feedback` with `{thread_id, content, author}`.
4. If no: handles normally as a chat message.
5. `newsfromthefront-analyst` wakes on `discord-feedback`, reads the feedback, and updates `brief.md`.

---

## Testing Workflow

Three modes, each faster than the last:

| Mode | How | What it tests | Touches KB? |
|---|---|---|---|
| Full fresh test | `@cogent test` in Discord | End-to-end: ingest + search + analysis + report | No |
| Analyst-only | `cogent dr.alpha cogos channel send newsfromthefront:findings-ready ...` with `is_test: true` | Report formatting, analysis quality | No |
| Search-only | `cogent dr.alpha cogos channel send` to trigger researcher, then read findings file | Query generation, Perplexity result quality | No |

Use full fresh tests for tuning end-to-end output. Use analyst-only to iterate on report formatting without burning Perplexity credits. Use search-only to tune query generation independently.

---

## Required Secrets

| Key | Purpose |
|---|---|
| `cogent/perplexity_api_key` | Perplexity API access for `web_search` |
| `cogent/github_token` | GitHub REST API for repo ingestion |

---

## CogOS Enhancements (Desired)

These are not blockers — the application can be built without them — but they are real gaps that will recur with every new CogOS application.

### Enhancement #1: HTTP capability

GitHub repo ingestion currently requires writing raw Python HTTP code in `run_code()` using the `secrets` capability for the API key. A general-purpose `http` capability would make external API calls a clean, typed, auditable primitive rather than raw code:

```
http.get(url: string, headers: dict?) → {status: number, body: string}
http.post(url: string, body: dict, headers: dict?) → {status: number, body: string}
```

This would be useful for any cogent that needs to interact with external REST APIs (GitHub, Linear, Stripe, etc.) and avoids reimplementing HTTP boilerplate in every process.

---

## Out of Scope

- Multi-project support (single project per instance for now; `brief.md` is singular)
- Email delivery of reports
- Configurable per-project cadence (daily is hardcoded)
- Automatic competitor discovery without user confirmation
