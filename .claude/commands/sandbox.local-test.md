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

### 3. Boot the image and run init

```bash
COGTAINER=dev COGENT=alpha uv run cogos start cogos --daemon
COGTAINER=dev COGENT=alpha uv run cogos process run init --executor local
```

Expect: `Init complete` with all cogs started. If init fails with `'COGTAINER'`, make sure `COGTAINER=dev` is set.

### 4. Run diagnostics

```bash
COGTAINER=dev COGENT=alpha uv run cogos process run diagnostics --executor local --event '{"channel_name":"system:diagnostics"}'
```

The `--event` flag is required — diagnostics only runs when triggered via the `system:diagnostics` channel.

Expect: `Run completed` with pass/fail counts. External-service checks (asana, blob, web) will fail without API keys — that's normal.

### 5. Start dashboard and verify

```bash
COGTAINER=dev COGENT=alpha uv run cogos dashboard start
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

### 6. Re-run after code changes

If you changed image files (`images/**`), diagnostics code, or sandbox code:
```bash
COGTAINER=dev COGENT=alpha uv run cogos restart
COGTAINER=dev COGENT=alpha uv run cogos process run init --executor local
COGTAINER=dev COGENT=alpha uv run cogos process run diagnostics --executor local --event '{"channel_name":"system:diagnostics"}'
```

If you only changed dashboard code:
```bash
COGTAINER=dev COGENT=alpha uv run cogos dashboard reload
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `NameError: name 'time' is not defined` | Sandbox code needs `import time` — allowed modules are in `src/cogos/sandbox/executor.py` |
| `'COGTAINER'` KeyError | Set `COGTAINER=dev` in the environment |
| `Process not found: diagnostics` | Run `cogos start` then `cogos process run init --executor local` first |
| Diagnostics says "Ignoring wakeup" | Pass `--event '{"channel_name":"system:diagnostics"}'` |
| Dashboard port conflict | Check `uv run cogtainer status dev` for assigned ports |
| Frontend 404 | Run `cd dashboard/frontend && npm ci` then restart dashboard |
