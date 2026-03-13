# cogents-v1

Cogent runtime, infrastructure, and dashboard code.

## Local Quick Start

### Prerequisites

- `uv sync --all-extras`
- `cd dashboard/frontend && npm ci` the first time you run the dashboard
- AWS credentials for Bedrock if you want local executor runs to make LLM calls

### Run CogOS Locally

`cogent local ...` uses the JSON-backed `LocalRepository` instead of AWS-backed RDS/Lambda state. By default it persists to `~/.cogent/local/cogos_data.json`.

```bash
# Boot the default image into the local repo
cogent local cogos image boot cogent-v1 --clean

# Inspect what was loaded
cogent local cogos status

# Start the local executor loop
cogent local cogos run-local
```

In another terminal, you can trigger work and inspect runs:

```bash
# Send a message into a handled channel
cogent local cogos channel send io:discord:dm --payload '{"content":"hello","author":"tester","author_id":"1","channel_id":"2","message_type":"discord:dm","is_dm":true,"is_mention":false,"attachments":[],"embeds":[]}'

# Run a single scheduler tick instead of the long-running loop
cogent local cogos run-local --once

# Inspect recent runs
cogent local cogos run list --limit 5

# Run a process directly, without channel delivery
cogent local cogos process run discord-handle-message --local
```

### Bring Up The Dashboard Against Local State

The simplest path is:

```bash
cogent local dashboard serve --db local
```

This starts:

- FastAPI backend on `DASHBOARD_BE_PORT` (defaults to `8100`)
- Next.js frontend on `DASHBOARD_FE_PORT` (defaults to `5200`)

Open `http://localhost:5200` unless your repo root `.env` overrides the ports.

In local dev, the frontend derives the cogent name from the hostname, so the header will usually show `localhost`. The data still comes from the shared local JSON repo because `--db local` sets `USE_LOCAL_DB=1`.

If you want to run backend and frontend separately:

```bash
# Terminal 1
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100

# Terminal 2
cd dashboard/frontend && npm run dev
```

### More Detailed References

- [AGENTS.md](AGENTS.md) has the broader repo operating notes
- [tests/cogos/local_validation.md](tests/cogos/local_validation.md) has the step-by-step local validation checklist
- [docs/cogos/guide.md](docs/cogos/guide.md) has the longer CogOS guide
