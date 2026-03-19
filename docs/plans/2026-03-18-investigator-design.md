# Failure Triage & Investigation System

## Overview

A system daemon (`apps/investigator`) spawned by init that automatically detects failures, deduplicates them, spawns investigation coglets, and produces actionable fix proposals.

## Architecture

```
apps/investigator/
  cog.py               — daemon config (python executor)
  main.py              — daemon loop: subscribe, sweep, dedup, spawn
  investigate/
    cog.py             — one_shot LLM config
    main.md            — investigation coglet prompt
```

## Daemon (main.py)

**Trigger:** Hybrid wake
- Subscribes to `process:run:failed` channel (handler-based immediate wake)
- Subscribes to `system:alerts` channel (new alerts)
- Periodic sweep via `idle_timeout_ms=60000` to catch anything missed

**Dedup logic:**
- For run failures: key = `process_id`
- For alerts: key = `(alert_type, source)`
- Tracks active investigations in `data/investigator/active.json`
- On wake: query FAILED runs + unresolved alerts, skip if dedup key already active
- On child:exited: remove dedup key, allowing future re-investigation

**Spawn:** For each new unique failure, spawn `investigate` coglet with context passed via channel message.

## Investigation Coglet (investigate/main.md)

LLM-driven one_shot coglet that:
1. Queries run history for the failed process
2. Reads traces (capability_calls, file_ops)
3. Reads channel messages that triggered the failure
4. Reads source code from `/mnt/repo` and `/mnt/boot`
5. Forms root cause hypothesis

**Output (three destinations):**
1. `triage:proposals` channel — structured proposal dict
2. `/triage/{process_name}/{timestamp}.md` — persistent file
3. Discord DM to manager — human-readable summary

**Proposal schema:**
```python
{
    "failure_id": "dedup_key",
    "failure_summary": "...",
    "timeline": [...],
    "root_cause_hypothesis": "...",
    "proposed_fix": "...",
    "confidence": 0.85,
    "evidence": {
        "runs_examined": [...],
        "traces": [...],
        "source_files": [...]
    }
}
```

## Capabilities

**Daemon:** `history`, `procs`, `channels`, `dir`, `file`, `stdlib`, `alerts`
**Investigation coglet:** `history`, `channels`, `dir`, `file`, `stdlib`, `discord`, `alerts`

## Init Integration

- Create `system:alerts` and `triage:proposals` channels at boot
- Spawn investigator daemon via `_spawn_cog(manifest)`
- Add `manager_discord_id` to cogent identity secrets
