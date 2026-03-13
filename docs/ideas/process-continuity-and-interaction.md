# Process Continuity & Interaction Ideas

Inspired by Slate (randomlabs.ai) and VSM quick wins (moskov.coefficientgiving.org).

## 1. Cross-run continuity via compacted summaries

CogOS processes restart with clean context each run. Good for avoiding context rot, bad for continuity.

**Idea**: `me.process().summary` — a file the process auto-updates each run with a compressed summary of what happened. The scheduler injects it as context for the next run.

- Process writes: "Completed DOM module port. 14/19 tasks done. Blocked on MessageManager compat issue."
- Next run sees this immediately without loading full history
- Auditable — dashboard shows the summary file

## 2. Human-in-the-loop decision points

Processes currently run to completion or failure. No way to pause for human input.

**Idea**: `me.ask(question, options)` — emits a `process:question` event and suspends the process.

```python
choice = me.ask(
    "MessageManager has a structural mismatch. How to fix?",
    options=["Bridge adapter", "Refactor to use AgentHistoryList", "Skip for now"]
)
# process suspends, user sees question in dashboard, clicks an option
# process resumes with choice = "Refactor to use AgentHistoryList"
```

Dashboard shows pending questions with clickable options. User clicks → `process:answer` event → process resumes.

This enables the "80/20" model: process works autonomously, pauses at decision points for human judgment.

## 3. Live progress tracking

Processes are black boxes during a run.

**Idea**: `me.run().progress(step, status)` writes structured progress to the event log.

```python
me.run().progress("convert_dom", "complete")
me.run().progress("convert_browser", "in_progress")
```

Dashboard shows live progress per running process. Events: `process:progress {step: "convert_dom", status: "complete"}`.

## 4. Research-then-execute two-phase runs

Slate plans implicitly by researching first, then presenting a plan, then executing.

**Idea**: Two-phase run model for complex tasks.

- Phase 1 (research): Process reads files, events, scratch dir. Writes a plan to `me.process().scratch_dir().write("plan.md", ...)`. Emits `process:plan:ready`.
- User reviews plan in dashboard, approves or edits.
- Phase 2 (execute): Process follows its own plan.

The scheduler could enforce this: first run = research, approval gate, second run = execute.

## 5. Fan-out / map-reduce on procs

RLM pattern from VSM: split input into chunks, spawn sub-agents in parallel, collect results.

**Idea**: `procs.fan_out(task_list, capabilities)` — spawns N child processes, waits for all to complete, aggregates results.

```python
results = procs.fan_out(
    tasks=[
        {"name": "audit-repo-1", "content": "Audit repo-1 for security issues"},
        {"name": "audit-repo-2", "content": "Audit repo-2 for security issues"},
    ],
    capabilities={"dir": dir.scope("/repos/", ops=["read"])},
)
```

The scheduler already handles parallel dispatch. This just needs a higher-level API.

## 6. Structured per-process memory

Letta-style typed memory blocks, native to CogOS.

**Idea**: Structured memory in `me.process().scratch_dir()`:
- `persona.md` — how the process should behave
- `lessons.md` — what it learned from past runs
- `preferences.md` — user corrections and feedback

Processes read these at start, append at end. Persists across runs. Dashboard shows/edits them.

## 7. Build-verify process pattern

For code-generation workflows: process writes code, separate process verifies it.

**Idea**: Standard image template with:
- `coder` process: writes code to `scratch/`, emits `code:written`
- `verifier` process: handler for `code:written`, runs tests, emits `code:verified` or `code:failed`
- `coder` handles `code:failed`, iterates

Multi-process instead of single-agent loop — cleaner separation of concerns.

## Priority

| # | Feature | Effort | Impact |
|---|---------|--------|--------|
| 1 | Cross-run summary compaction | Small | High — continuity without rot |
| 2 | `me.ask()` decision points | Medium | High — enables 80/20 autonomy |
| 3 | Live progress tracking | Small | Medium — visibility during runs |
| 4 | Fan-out / map-reduce | Medium | High — parallel workloads |
| 5 | Two-phase research/execute | Medium | Medium — better plans |
| 6 | Structured process memory | Small | Medium — cross-run learning |
| 7 | Build-verify pattern | Small | Medium — code quality loops |
