# Processes

A process is the only active entity in CogOS. It has a lifecycle, priority, resource requirements, and a set of bound capabilities. It executes by running a prompt through an LLM that writes Python against capability proxy objects.

## Modes

**Daemon** — runs indefinitely. Completes a run, returns to WAITING for the next matching channel message. Must have at least one handler (channel subscription).

**One-shot** — runs once and completes. Cannot have handlers. Used for batch jobs, subtasks, and child work spawned by daemons.

## Lifecycle

```
            channel message
  WAITING ──────────────> RUNNABLE
     ^                        |
     |                        |-- resources available --> RUNNING
     |                        |                             |
     |                        '-- resources exhausted --> BLOCKED
     |                                                     |
     |                        resources freed              |
     |                        BLOCKED ------> RUNNABLE     |
     |                                                     |
     |  done + daemon ─────────────────────────────────────+
     |                                                     |
     '─────────────────────────────────────────────────────+
                                                           |
                            done + one_shot --> COMPLETED  |
                            failed + retries --> RUNNABLE  |
                            failed + exhausted -> DISABLED |
```

| State | Meaning |
|---|---|
| WAITING | Sleeping. Wakes when a message arrives on a subscribed channel. |
| RUNNABLE | Ready to run. Waiting for the scheduler to dispatch. |
| RUNNING | Currently executing. |
| BLOCKED | Runnable but resources unavailable. |
| SUSPENDED | Preempted mid-execution. |
| COMPLETED | Finished (one-shot only). |
| DISABLED | Permanently stopped (retries exhausted or manually disabled). |

## Priority and scheduling

Priority is a float. Higher = more likely to be selected. The scheduler uses softmax sampling, not strict ordering, so lower-priority processes still have a chance.

Starvation prevention: `effective_priority = priority + f(now - runnable_since)`. A process that has been RUNNABLE for a long time gets boosted.

## Spawning children

A running process can spawn one-shot child processes:

```python
child = procs.spawn(
    "reindex-chunk-42",
    content="Reindex documents 4200-4299",
    capabilities={
        "workspace": dir.scope("/data/", ops=["read", "write"]),
        "channels": channels,
    },
)
```

Children:
- Are always one-shot
- Set the parent as `parent_process`
- Start in RUNNABLE
- Do NOT inherit capabilities — pass them explicitly

## Runners

**Lambda** — short-lived, stateless. The executor Lambda runs a Bedrock converse loop with search + run_code tools. Good for reasoning, API calls, data operations.

**ECS** — long-running, stateful. Claude Code CLI runs in a Fargate container with an MCP server. Good for software engineering, git, filesystem work.

## Model selection

Processes can target specific models:

```python
add_process("cheap-classifier", model="us.anthropic.claude-haiku-4-5-20251001-v1:0", ...)
add_process("complex-reasoner", model="us.anthropic.claude-sonnet-4-20250514-v1:0", ...)
```

Route cheap tasks to Haiku, complex tasks to Sonnet or Opus.

## Retries

Processes can configure retry behavior:
- `max_retries` — how many times to retry on failure (default 0)
- `retry_backoff_ms` — delay before retry
- After exhausting retries, the process goes to DISABLED

## Resource requirements

Processes declare required resources. The scheduler checks availability before dispatch:
- **Pool resources** (e.g., `lambda-slots`): concurrent usage slots
- **Consumable resources** (e.g., `daily-budget`): finite per period

If resources are unavailable, the process goes to BLOCKED and is rechecked each tick.
