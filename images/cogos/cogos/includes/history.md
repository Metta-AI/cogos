# History

Query run history and file mutations across processes.

## Per-process history

```python
h = history.process("worker-3")

# Recent runs
for run in h.runs(limit=5):
    print(f"{run.status} {run.duration_ms}ms {run.error or ''}")

# Files mutated by a run
for f in h.files(run_id=run.id):
    print(f"  {f.key} v{f.version}")
```

## Cross-process queries

```python
# All failed runs
for run in history.failed(since="1h"):
    print(f"{run.process_name}: {run.error}")

# Custom query
runs = history.query(
    process_name="worker-*",
    status="failed",
    since="2026-03-17T00:00",
    limit=50,
)
```

## Return types

- `RunSummary` — id, process_id, process_name, status, duration_ms, tokens_in, tokens_out, cost_usd, error, result, model_version, created_at, completed_at
- `FileMutation` — key, version, created_at
- `HistoryError` — error (string)

Check for errors: `if isinstance(result, HistoryError): print(result.error)`
