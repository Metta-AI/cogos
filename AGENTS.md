# Cogent — Autonomous Software Engineering Agent

Built on the Viable System Model. Each cogent is an autonomous agent with its own ECS task, database, and channel integrations.

## Project Layout

```
src/
  body/         # Agent runtime (ECS task)
  brain/        # LLM reasoning engine
  mind/         # Agent personality and goals
  memory/       # Persistent memory (PostgreSQL)
  channels/     # External integrations (Discord, GitHub, Asana)
  cli/          # Main cogent CLI
  polis/        # Shared infrastructure hub (see docs/polis/)
docs/
  polis/        # Polis design and CLI reference
tests/
```

## Polis — Shared Infrastructure

Polis manages the shared AWS resources that all cogents depend on: ECS cluster, ECR container registry, Route53 DNS, secrets, and monitoring.

- **Design**: [docs/polis/design.md](docs/polis/design.md) — Architecture, module structure, resource details
- **CLI Reference**: [docs/polis/cli.md](docs/polis/cli.md) — All commands with examples and options

Key commands:

```bash
polis status                     # Show infrastructure health
polis secrets list --cogent NAME # List a cogent's secrets
polis cogents list               # All cogents with CPU/memory/channels
```

## AWS Infrastructure

- **Organization**: o-n7g18rzou1
- **Polis account**: 901289084804 (us-east-1)
- **ECR**: 901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent
- **Domain**: softmax-cogents.com
- **Auth profile**: `softmax-org` (SSO admin on management account 111005867451)

## Secret Path Conventions

```
cogent/{name}/{channel}    # Per-cogent channel creds (e.g., cogent/alpha/discord)
polis/shared/{key}         # Org-wide shared keys (e.g., polis/shared/jwt-signing-key)
```

## Dashboard Testing with agent-browser

Use the `agent-browser` skill to test the Cogent Dashboard interactively.

### Prerequisites

Start the dashboard backend and frontend:

```bash
# Terminal 1: Backend (FastAPI on port 8100)
uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100 --reload

# Terminal 2: Frontend (Next.js on port 5174)
cd dashboard/frontend && npm run dev
```

### Quick Start

```bash
npx agent-browser open http://localhost:5174 && npx agent-browser wait --load networkidle && npx agent-browser snapshot -i
```

### Dashboard Panels to Test

The dashboard uses CogOS routers. Key tabs:

| Tab | Description | Key interactions |
|-----|-------------|-----------------|
| Overview | CogOS status, process counts, recent runs | Verify stat rendering |
| Processes | Process list with detail panel | Click rows to open detail |
| Files | File browser with version history | Click rows, edit versions |
| Capabilities | Capability list with method introspection | Click rows for detail |
| Handlers | Event handler list with fire counts | View handler patterns |
| Runs | Run history with scope logs | Click for run detail |
| Events | Event log with tree view | Expand events, click tree |
| Cron | Cron rules with toggle switches | Toggle on/off, create/edit |

### Testing Workflow

```bash
# Open dashboard and orient
npx agent-browser open http://localhost:5174
npx agent-browser wait --load networkidle
npx agent-browser snapshot -i

# Click through each sidebar tab
npx agent-browser click @e{N}  # Use ref from snapshot for sidebar tab
npx agent-browser wait --load networkidle
npx agent-browser snapshot -i

# Test interactive elements (expand rows, toggle switches, etc.)
npx agent-browser click @e{N}
npx agent-browser snapshot -i

# Check for console errors
npx agent-browser console

# Take annotated screenshots for visual review
npx agent-browser screenshot --annotate ./test-output/dashboard.png
```

### Dogfooding

For a full QA pass, use the `dogfood` skill:

```
/dogfood http://localhost:5174
```

This will systematically explore the dashboard, document issues with screenshots and repro videos, and produce a structured report.

### API Endpoints

The backend serves REST API under `/api/cogents/{name}/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/healthz` | GET | Health check |
| `/api/cogents/{name}/status` | GET | Cogent status |
| `/api/cogents/{name}/programs` | GET | Programs list |
| `/api/cogents/{name}/sessions` | GET | Sessions list |
| `/api/cogents/{name}/events` | GET | Events log |
| `/api/cogents/{name}/events/{id}/tree` | GET | Event causal tree |
| `/api/cogents/{name}/triggers` | GET | Triggers list |
| `/api/cogents/{name}/triggers/toggle` | POST | Toggle trigger |
| `/api/cogents/{name}/memory` | GET | Memory items |
| `/api/cogents/{name}/tasks` | GET | Task queue |
| `/api/cogents/{name}/channels` | GET | Channels |
| `/api/cogents/{name}/alerts` | GET | Unresolved alerts |
| `/api/cogents/{name}/resources` | GET | Active resources |
| `/ws/cogents/{name}` | WS | Real-time updates |

### Architecture

- **Backend**: FastAPI + RDS Data API, port 8100
- **Frontend**: Next.js 15 + React 19 + Tailwind v4, port 5174
- **Real-time**: WebSocket via PostgreSQL LISTEN/NOTIFY
- **Auth**: API key in `x-api-key` header (SHA-256 hashed, stored in Secrets Manager)

### Database Connection

Both the dashboard and `mind` CLI require RDS Data API credentials (`DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`). Set `USE_LOCAL_DB=1` to use LocalRepository (JSON file at `~/.cogent/local/data.json`) for local dev without AWS.

## Development

When starting a new task with a clean repo, always pull latest first:

```bash
git pull origin main          # Sync with remote before starting work
uv sync --all-extras          # Install dependencies
uv run pytest                 # Run tests
uv run polis status           # Check infrastructure
```

## Git Workflow

- Do not push directly to `main` unless the user explicitly asks for that push in the current conversation.
- If a change is ready but push behavior is not specified, make a Graphite PR instead of pushing or merging directly to `main`.

## PR Writeups

When writing PR titles, descriptions, or review comments:

- Start with a `Problem` section that explains the prior behavior or source of churn, not just the code change.
- Phrase the problem in operational terms: what was ambiguous, brittle, inconsistent, or targeting the wrong thing.
- Use a `Summary` section for the concrete behavioral changes the diff makes.
- Keep summary bullets specific about user-visible or operator-visible semantics, not file-by-file edits.
- End with a `Testing` section listing the exact verification commands that were run.
- Prefer wording like “this command could do X” or “this flow had no explicit way to choose Y” over vague claims like “cleanup” or “improves things.”
- If the change fixes the wrong target or wrong environment being selected, say that explicitly in the problem statement.
