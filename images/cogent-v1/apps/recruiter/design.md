# Recruiter App Design

A self-improving CogOS application that finds and profiles potential employees, targeting people working on coding agents and orchestration frameworks.

## Process Architecture

Five CogOS processes in a tree:

- **`recruiter`** (daemon, root) — orchestrator. Owns criteria, scoring rubric, and self-improvement logic. Schedules discovery runs, manages the candidate pool, decides when to spawn `evolve`.
- **`recruiter/discover`** (one-shot, spawned per run) — batch discovery across all sources. Scores candidates against current rubric. Writes raw candidates to the pool.
- **`recruiter/present`** (daemon) — drip-feeds screened candidates to Discord conversationally. Asks targeted questions to refine understanding. Captures feedback.
- **`recruiter/profile`** (one-shot, spawned per candidate) — generates deep-dive HTML report for candidates that pass screening. Writes to file store, linked on dashboard.
- **`recruiter/evolve`** (one-shot, spawned when needed) — diagnoses feedback patterns, proposes changes with progressive escalation, posts approval requests to Discord, applies approved changes.

## File Structure

Configuration and prompts live in `apps/recruiter/`. All persistent data lives in `data/recruiter/`:

```
apps/recruiter/                # Configuration & prompts (read-mostly)
  criteria.md              # What we want: skills, background, values, red flags
  rubric.json              # Scoring weights: {"github_activity": 0.3, ...}
  diagnosis.md             # How to classify feedback gaps, escalation thresholds
  strategy.md              # Operational prompts: search priorities, presentation style
  evolution.md             # Changelog of self-modifications (audit trail)

  sourcer/
    github.md              # How to search GitHub, what signals matter, queries
    twitter.md             # How to search Twitter/X, signal vs noise criteria
    web.md                 # Web search strategy: conferences, blogs, HN, podcasts
    substack.md            # Newsletter discovery, depth/consistency signals

data/recruiter/                # Persistent storage (read-write, via `data` capability)
  session.md               # Recent activity log (managed by compact/session memory policy)
  summary.md               # Long-term learnings (managed by compact memory policy)
  feedback.jsonl           # Append-only log of all feedback with source/context

  candidates/
    {handle}.json          # Per-candidate structured data: profiles, scores, status, feedback
    {handle}.html          # Deep-dive standalone HTML report
```

### Context Engine Wiring

- `recruiter` process attaches `criteria.md` and `strategy.md` via includes — injected into system prompt automatically.
- `discover` process includes all `sourcer/*.md` files plus `criteria.md` and `rubric.json`.
- `evolve` process includes `diagnosis.md`, `criteria.md`, `rubric.json`, `strategy.md`, and recent `feedback.jsonl` entries.

## Self-Improvement Engine

### Trigger

Root `recruiter` spawns `evolve` after accumulating N pieces of feedback (e.g., 5), or when it detects a pattern (e.g., 3 consecutive rejections).

### Progressive Escalation

`evolve` follows `diagnosis.md` to classify the gap, always trying the cheapest fix first:

1. **Calibration error** — candidates match criteria but score wrong → adjust `rubric.json` weights. Can auto-apply.
2. **Criteria gap** — missing or wrong dimension → patch `criteria.md`. Requires Discord approval.
3. **Strategy error** — looking in wrong places or asking wrong queries → rewrite `strategy.md` or individual `sourcer/*.md`. Requires Discord approval.
4. **Code/process error** — fundamental approach is broken → modify process code/prompts. Requires Discord approval.

### Diagnosis

`diagnosis.md` is itself a modifiable file describing:
- How to classify feedback into error types
- What constitutes each error type
- Escalation thresholds (e.g., "3 similar rejections before proposing criteria change")
- What can be auto-applied vs what needs approval

`evolve` can propose changes to `diagnosis.md` itself (with approval), making the meta-learning process also self-improving.

### Flow

1. **Diagnose** — analyze recent feedback against current rubric, criteria, strategy
2. **Propose** — generate the specific change with reasoning and triggering feedback
3. **Approve** — post to Discord conversationally, wait for response
4. **Apply** — write the change, log to `evolution.md`, next run picks it up

## Discord Integration

The `present` process uses Discord conversationally — no card/embed style.

### Candidate Presentations

Posts a summary with a pointed question:

> "Found someone interesting — @jsmith has been building a multi-agent orchestration layer on top of LangGraph. 800 stars, active for 6 months, writes detailed Substack posts about agent reliability patterns. Their approach is opinionated about synchronous tool calls vs async — do we care about that architectural stance, or just that they're deep in the orchestration space?"

### Approval Requests (from `evolve`)

> "After 3 rejections of academics with no shipping history, I think 'has shipped production agent systems' should be an explicit criterion. Approve?"

### Clarifying Questions (proactive)

> "I'm finding a cluster of people building agents in Rust. So far we've only looked at Python/TS. Should I expand the language criteria, or is Python/TS ecosystem experience important for team fit?"

Responses are captured as feedback entries. The process parses intent (approval, rejection, preference signal, clarification) and routes accordingly.

## Source-Specific Discovery

Each source has its own `sourcer/*.md` file defining search strategy:

### GitHub (`sourcer/github.md`)
- Search repos tagged with agent/orchestration keywords (langchain, crewai, autogen, agent framework, tool-use, MCP, etc.)
- Profile top contributors: commit frequency, code quality (PR reviews, issue discussions), repo ownership vs contribution
- Focus on what they've built, not what they've starred

### Twitter/X (`sourcer/twitter.md`)
- Search for accounts posting about agent development, LLM orchestration, tool-use patterns
- Signal: original technical threads, engagement from other builders, building-in-public content
- Follower quality over quantity, ratio of technical to non-technical posts

### Web Search (`sourcer/web.md`)
- Conference talks, blog posts, HN comments, podcast appearances
- Catches people not active on GitHub/Twitter but known in the space

### Substack (`sourcer/substack.md`)
- Newsletters covering agent development, LLM engineering, orchestration patterns
- Signal: depth of writing, consistency, original thinking vs summarizing

Each source produces raw candidate records merged by root process (deduplicated by identity matching). Relative source value tracked in `strategy.md` and adjusted by `evolve`.

## Dashboard

Four views served via the existing CogOS dashboard:

### Pipeline View
Candidates grouped by status: discovered → screened → profiled → actioned → archived. Sortable by score, recency, source. Click through to deep-dive report.

### Candidate Detail
Renders `{handle}.html` inline. Below it, free-form text input for feedback. Feedback appended to `feedback.jsonl` tagged with candidate/timestamp.

### Evolution Log
`evolution.md` rendered as timeline. What changed, when, why, approved/rejected. Shows how the system's taste has evolved.

### Criteria Editor
Live view of `criteria.md`, `rubric.json`, and `diagnosis.md`. Editable directly (treated as manual feedback, logged). Or let `evolve` propose changes.

## Asana Integration

One Asana task per candidate when they pass screening:
- Task title: candidate name
- Description: profile summary with link to HTML report
- Track through pipeline stages via Asana sections (Research → Outreach → Interview → Offer)

## Capabilities Required

Each process gets scoped capabilities:

- `recruiter`: me, procs (spawn), files, events, discord, asana
- `recruiter/discover`: me, files (write to candidates/), web search
- `recruiter/present`: me, files (read candidates, read/write feedback), discord
- `recruiter/profile`: me, files (read candidate json, write candidate html)
- `recruiter/evolve`: me, files (read/write criteria, rubric, diagnosis, strategy, sourcer/*, evolution), discord, procs (optional — for code-level changes)
