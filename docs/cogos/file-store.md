# CogOS File Store and `/proc` Namespace

CogOS stores both human-authored files and runtime artifacts in the same versioned file store.

This page is only about the runtime side: the `/proc/{process_id}/...` namespace that the executor and the `me` capability use.

## Top-Level Shape

For a process `P` and run `R`, the important runtime keys are:

```text
/proc/{process_id}/
  tmp
  scratch
  log
  runs/{run_id}/
    tmp
    scratch
    log
  _sessions/{session_path}/
    manifest.json
    checkpoint.json
    runs/{run_id}/
      trigger.json
      steps/{seq}.json
      final.json
```

## What Each Area Is For

| Path | Owner | Purpose |
|---|---|---|
| `/proc/{process_id}/tmp` | process code | Small process-scoped temporary state |
| `/proc/{process_id}/scratch` | process code | Process-scoped working data that can persist across runs |
| `/proc/{process_id}/log` | process code | Process-scoped log file if the process chooses to write one |
| `/proc/{process_id}/runs/{run_id}/tmp` | process code | Run-scoped temporary state |
| `/proc/{process_id}/runs/{run_id}/scratch` | process code | Run-scoped scratch data |
| `/proc/{process_id}/runs/{run_id}/log` | process code | Run-scoped log file if the process chooses to write one |
| `/proc/{process_id}/_sessions/...` | executor | Resume checkpoints and immutable execution artifacts |

The important boundary is:

- `tmp`, `scratch`, and `log` are the process-facing writable areas exposed by `me`.
- `_sessions` is executor-owned bookkeeping. It is where the executor writes resumable state and per-run artifacts.

## Session Path Naming

The `_sessions` directory is partitioned by `session_path`:

```text
session_path = "{mode}-{hash}"
```

Where:

- `mode` comes from `process.metadata["session"]["mode"]`
- `hash` is the first 16 hex chars of `sha256(logical_session_key)`

The hash is there so file keys do not embed raw user text or arbitrary payload strings.

### Modes

| Mode | Meaning |
|---|---|
| `off` | Resume is off. The executor still writes run artifacts, but it never loads a checkpoint. |
| `process` | One rolling resumable session per process. The executor may load `checkpoint.json` if it is valid. |
| `keyed` | Intended for event-keyed sessions. The logical key comes from an event payload field. In the current implementation, this mode is parsed but resume is not yet enabled. |

So a path like:

```text
/proc/{process_id}/_sessions/off-37a8eec1ce19687d/
```

means:

- `off`: this session namespace is logging-only, not resumable
- `37a8eec1ce19687d`: stable hash of the logical session key

For both `off` and `process`, the default logical session key is currently `"default"` unless a keyed mode is used later.

## Session Artifact Files

Within one session namespace:

| File | Mutable | Meaning |
|---|---|---|
| `manifest.json` | yes | Small session-level index: latest run, latest final artifact, checkpoint pointer, mode metadata |
| `checkpoint.json` | yes | Resumable Bedrock message state for the active session |
| `runs/{run_id}/trigger.json` | no | The incoming event payload plus the synthesized user message for that run |
| `runs/{run_id}/steps/{seq}.json` | no | Ordered executor state transitions for the run |
| `runs/{run_id}/final.json` | no | Final run outcome and pointers back to the other artifacts |

The split is intentional:

- `manifest.json` and `checkpoint.json` stay small and can be updated in place
- `trigger.json`, `steps/*.json`, and `final.json` are immutable, so operators can inspect exactly what happened in a run

## Reading a Run

If you are trying to understand one run, start here:

1. `Run.snapshot.final_key`
2. `final.json`
3. `trigger.json`
4. `steps/*.json`
5. `checkpoint.json` and `manifest.json` if you need session context

`final.json` is the best entry point because it points to the run's `trigger_key`, `steps_key`, and the relevant session files.

## Operator Notes

- Seeing `off-...` in `_sessions` does not mean the session system is broken. It means artifacts are being written, but resume is intentionally disabled for that process.
- The dashboard run-log foldout reads these executor-owned artifacts directly.
- Raw Python logger output from the executor is separate from these files. In AWS it goes to CloudWatch. In local `run-local`, it goes to the local process stdout/stderr unless captured elsewhere.
- Processes should treat `_sessions` as executor-owned state, not as a general-purpose scratch area.
