Ensure a local cogent is running. Idempotent — safe to run at the start of every session.

Use this before testing code changes locally, especially in remote/headless sessions.

## Steps

### 1. Install dependencies

```bash
uv sync
```

### 2. Ensure cogtainer exists

```bash
uv run cogtainer list
```

If no local cogtainer named `dev` exists:
```bash
uv run cogtainer create dev --type local --llm-provider anthropic --llm-model claude-sonnet-4-20250514 --llm-api-key-env ANTHROPIC_API_KEY
```

### 3. Ensure cogent exists

```bash
uv run cogent list
```

If no cogent named `alpha` exists:
```bash
uv run cogent create alpha
```

### 4. Ensure selection is persisted

Check if `.env` already has `COGENT=alpha`:
```bash
grep -q 'COGENT=alpha' .env 2>/dev/null
```

If not:
```bash
uv run cogent select alpha
```

### 5. Start or restart CogOS

Check if the dispatcher is already running:
```bash
pgrep -f 'cogos.cli.*start.*--foreground' > /dev/null 2>&1
```

If running, restart (picks up code changes):
```bash
uv run cogos restart
```

If not running, start fresh:
```bash
uv run cogos start
```

### 6. Verify

```bash
uv run cogos status
```

Print: `Local cogent ready. Run /sandbox.local-test for full diagnostics + dashboard.`
