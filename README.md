# cogents-v1

Cogent runtime, infrastructure, and dashboard code.

## Local Quick Start

### 1. Install Dependencies

```bash
uv sync --all-extras
cd dashboard/frontend && npm ci && cd ../..
```

You need both steps. The `npm ci` installs Next.js for the dashboard frontend — without it, the dashboard will fail to start.

AWS credentials with Bedrock access are required for the local executor to make LLM calls.

### 2. Load an Image

`cogent local ...` uses the JSON-backed `LocalRepository` instead of AWS-backed RDS/Lambda state. Data persists to `~/.cogent/local/cogos_data.json`.

Images live in `images/`. The main image is `cogent-v1`. App-specific images are under `images/apps/` (e.g., `apps/newsfromthefront`).

```bash
# Load the default cogent-v1 image (wipes and reloads)
uv run cogent local cogos reload -i cogent-v1 -y

# Or boot a specific app image
uv run cogent local cogos image boot apps/newsfromthefront --clean
```

Verify what was loaded:

```bash
uv run cogent local cogos status
```

You should see processes, channels, capabilities, and files listed.

### 3. Start the Local Executor

In one terminal, start the executor loop. This replaces Lambda dispatch — it polls for work every 2 seconds and runs processes via Bedrock.

```bash
uv run cogent local cogos run-local
```

### 4. Trigger Work

In another terminal, send messages to channels to trigger processes:

```bash
# Send a message into a handled channel
uv run cogent local cogos channel send io:discord:dm --payload '{"content":"hello","author":"tester","author_id":"1","channel_id":"2","message_type":"discord:dm","is_dm":true,"is_mention":false,"attachments":[],"embeds":[]}'

# Run a single scheduler tick instead of the long-running loop
uv run cogent local cogos run-local --once

# Inspect recent runs
uv run cogent local cogos run list --limit 5

# Run a process directly, without channel delivery
uv run cogent local cogos process run discord-handle-message --local
```

### 5. Start the Dashboard

```bash
uv run cogent local cogos dashboard start
```

This starts the FastAPI backend and Next.js frontend. The URL will be printed (usually `http://localhost:29489`).

Other dashboard commands:

```bash
uv run cogent local cogos dashboard reload   # stop + start
uv run cogent local cogos dashboard stop     # stop both
```

Check logs if something goes wrong:

```bash
cat /tmp/cogent-backend.log
cat /tmp/cogent-frontend.log
```

If you want to run backend and frontend separately:

```bash
# Terminal 1
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100

# Terminal 2
cd dashboard/frontend && npm run dev
```

### Troubleshooting

**Dashboard frontend fails to start:** Run `cd dashboard/frontend && npm ci` first. The `dashboard start` command uses `npx next` which will prompt to install Next.js and fail in non-interactive mode.

**Executor runs but nothing happens:** Check that handlers exist with `uv run cogent local cogos handler list`. If empty, re-run `reload` or `image boot --clean` — handlers link channels to processes.

**LLM calls fail:** Ensure AWS credentials are configured and Bedrock model access is enabled in your account/region.

### More Detailed References

- [AGENTS.md](AGENTS.md) has the broader repo operating notes
- [tests/cogos/local_validation.md](tests/cogos/local_validation.md) has the step-by-step local validation checklist
- [docs/cogos/guide.md](docs/cogos/guide.md) has the longer CogOS guide
