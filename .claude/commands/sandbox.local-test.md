Launch a local cogtainer and cogent, run diagnostics, and start the dashboard.

Use this after code changes to verify everything works end-to-end in a local sandbox — no AWS credentials needed for diagnostics (Python executor).

## Steps

### 1. Install dependencies (skip if already done this session)

```bash
uv sync
cd dashboard/frontend && npm ci && cd ../..
```

### 2. Create cogtainer and cogent (skip if they already exist)

Check first:
```bash
uv run cogtainer list
```

If no local cogtainer exists:
```bash
uv run cogtainer create dev --type local --llm-provider anthropic --llm-model claude-sonnet-4-20250514 --llm-api-key-env ANTHROPIC_API_KEY
uv run cogent create alpha
```

### 3. Ensure selection is persisted to .env

**IMPORTANT**: `cogos` commands require both `COGTAINER` and `COGENT` in the repo-local `.env` file. Without these, process runs will crash with `KeyError: 'COGTAINER'`. Always verify, even if the cogtainer/cogent already existed.

```bash
grep -q 'COGTAINER=' .env 2>/dev/null && grep -q 'COGENT=' .env 2>/dev/null
```

If either is missing, run `cogent select` which writes both:
```bash
uv run cogent select alpha
```

### 4. Boot the image and start dispatcher

```bash
uv run cogos start
```

This boots the image and starts the dispatcher, which automatically runs init. Expect: `Boot complete` followed by `Dispatcher started in background`.

### 5. Run diagnostics

```bash
uv run cogos process run diagnostics --executor local --event '{"channel_name":"system:diagnostics"}'
```

The `--event` flag is required — diagnostics only runs when triggered via the `system:diagnostics` channel.

Expect: `Run completed` with pass/fail counts. External-service checks (asana, blob, web) will fail without API keys — that's normal.

### 6. Start dashboard and verify

```bash
uv run cogos dashboard start
```

Verify diagnostics are visible:
```bash
curl -s http://localhost:8100/api/cogents/alpha/diagnostics | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d['summary']
print(f'Diagnostics: {s[\"pass\"]}/{s[\"total\"]} passed, {s[\"fail\"]} failed')
for cat in sorted(d['categories']):
    c = d['categories'][cat]
    print(f'  {cat}: {c[\"status\"]}')
"
```

Print: `Dashboard running at http://localhost:5200 — diagnostics visible`

### 7. Re-run after code changes

If you changed image files (`images/**`), diagnostics code, or sandbox code:
```bash
uv run cogos restart
uv run cogos process run diagnostics --executor local --event '{"channel_name":"system:diagnostics"}'
```

If you only changed dashboard code:
```bash
uv run cogos dashboard reload
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `NameError: name 'time' is not defined` | Sandbox code needs `import time` — allowed modules are in `src/cogos/sandbox/executor.py` |
| `'COGTAINER'` KeyError | Run `uv run cogent select alpha` to persist selection to `.env` |
| `Process not found: diagnostics` | Run `cogos start` first (boots image and runs init via dispatcher) |
| Diagnostics says "Ignoring wakeup" | Pass `--event '{"channel_name":"system:diagnostics"}'` |
| Dashboard port conflict | Check `uv run cogtainer status dev` for assigned ports |
| Frontend 404 | Run `cd dashboard/frontend && npm ci` then restart dashboard |
| Any silent failure | Run `uv run cogent status` to find log_dir, then read the relevant log below |

### Log files

All logs live under the cogent's log directory (shown by `uv run cogent status`):

| Log file | Source |
|----------|--------|
| `dispatcher.log` | Dispatcher daemon (step 4) |
| `executor.log` | Executor subprocess (step 5) |
| `dashboard-backend.log` | Dashboard API server (step 6) |
| `dashboard-frontend.log` | Dashboard Next.js dev server (step 6) |
