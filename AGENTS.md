# Cogent — Autonomous Software Engineering Agent

Built on the Viable System Model. Each cogent is an autonomous agent with its own ECS task, database, and channel integrations.

## Project Layout

```
src/
  cogtainer/    # Persistent state, DB, infrastructure (firmware)
  cogos/        # Execution engine (operating system)
  memory/       # Persistent memory (PostgreSQL)
  cogos/io/     # External IO (Discord, GitHub, Asana, email)
  cli/          # Main cogent CLI
  polis/        # Shared infrastructure hub (see docs/polis/)
  dashboard/    # Operational dashboard
  body/         # Agent runtime (ECS task)
  run/          # Run management CLI
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

## Running a Cogent Locally vs on AWS

`-c local` means run on this machine using LocalRepository (JSON file at `~/.cogent/local/cogos_data.json`). Any other `-c` value (e.g., `-c dr.alpha`) targets the named cogent's AWS infrastructure (RDS, Lambda, ECS).

### Local: Run CogOS on this machine

Requires AWS credentials for Bedrock (LLM calls). No Lambda, no RDS, no EventBridge.

```bash
# 1. Boot an image into local DB
cogent local cogos image boot cogent-v1 --clean

# 2. Start the local executor (daemon loop, replaces Lambda dispatch)
cogent local cogos run-local

# 3. (Optional) Start Discord bridge locally
cogent local cogos io discord run-local

# 4. Run a single process manually
cogent local cogos process run <process-name> --local

# 5. Check status
cogent local cogos status
cogent local cogos run list
```

`run-local` options:
- `--poll-interval 5` — change polling frequency (default 2s)
- `--once` — run one tick and exit (useful for testing)

### Validated Local Operations

All of the following have been tested and work with `cogent local`:

| Operation | Command |
|-----------|---------|
| Boot image | `cogent local cogos image boot cogent-v1 --clean` |
| Check status | `cogent local cogos status` |
| List capabilities | `cogent local cogos capability list` |
| Inspect capability | `cogent local cogos capability get <name>` |
| List/read/create files | `cogent local cogos file list`, `file get`, `file create` |
| List handlers | `cogent local cogos handler list` |
| Emit channel message | `cogent local cogos event emit <channel> --payload '{...}'` |
| Run executor tick | `cogent local cogos run-local --once` |
| Run process directly | `cogent local cogos process run <name> --local` |
| Disable process | `cogent local cogos process disable <name>` |
| View run history | `cogent local cogos run list`, `run show <id>` |
| Wipe all data | `cogent local cogos wipe -y` |
| Reload from image | `cogent local cogos reload -i cogent-v1 -y` |
| Discord IO help | `cogent local cogos io discord --help` |

Validation checklist with step-by-step commands: `tests/cogos/local_validation.md`

## Dashboard Ports

Ports are configured in the repo root `.env` file:

```
DASHBOARD_BE_PORT=8100    # FastAPI backend
DASHBOARD_FE_PORT=5200    # Next.js frontend dev server
```

In dev mode, the Next.js frontend proxies `/api/*` and `/ws/*` to the backend via `rewrites` in `next.config.ts`. You access the app at the **frontend port** (e.g., `http://localhost:5200`), and it forwards API calls to the backend port transparently.

In production (Docker), both are served on a single port (8100) — Next.js is statically exported and served by FastAPI.

### Starting the dashboard

```bash
# All-in-one (starts both backend + frontend, opens browser):
cogent dr.alpha dashboard serve --db local     # local DB
cogent dr.alpha dashboard serve --db prod      # live polis DB

# Manual (two terminals):
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8100
cd dashboard/frontend && npm run dev
```

`--db local` sets `USE_LOCAL_DB=1` (JSON file, no AWS needed). `--db prod` assumes into the polis account to get live RDS credentials.

## Remote Deployment and Testing

### Deploying the dashboard

```bash
cogent dr.alpha dashboard deploy              # Build frontend, push to ECR, restart ECS
cogent dr.alpha dashboard deploy --docker     # Force Docker image rebuild
```

This builds the Next.js static export, packages it with the FastAPI backend into a Docker image, pushes to ECR (`901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent`), and restarts the ECS Fargate service. The dashboard is served at `https://{safe-name}.softmax-cogents.com`.

### Deploying brain (Lambda + DB migrations)

```bash
cogent dr.alpha brain update                  # Update Lambda code + run DB migrations
cogent dr.alpha brain update stack            # Update CloudFormation stack (ALB rules, etc.)
```

### Managing the Discord bridge (remote)

```bash
cogent dr.alpha cogos io discord start     # Scale ECS service to 1 task
cogent dr.alpha cogos io discord stop      # Scale to 0
cogent dr.alpha cogos io discord restart   # Force new deployment
cogent dr.alpha cogos io discord status    # Check running/desired counts
```

### Testing a deployed dashboard

1. Create a PAT (Personal Access Token) for API access:

```bash
cogent dr.alpha dashboard create-pat
cogent dr.alpha brain update stack            # Apply ALB bypass rule
```

2. Test with curl:

```bash
curl -H 'X-Api-Key: <pat>' https://dr-alpha.softmax-cogents.com/api/cogents/dr.alpha/status
```

3. Or use the `dashboard.test` skill which automates PAT-authenticated UI and API testing against the deployed dashboard.

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
| `/api/cogents/{name}/cogos-status` | GET | CogOS status overview |
| `/api/cogents/{name}/processes` | GET | Process list |
| `/api/cogents/{name}/processes/{id}` | GET | Process detail |
| `/api/cogents/{name}/handlers` | GET | Event handler list |
| `/api/cogents/{name}/files` | GET | File browser |
| `/api/cogents/{name}/files/{key}` | GET | File detail with versions |
| `/api/cogents/{name}/capabilities` | GET | Capability list |
| `/api/cogents/{name}/capabilities/{name}/methods` | GET | Capability methods |
| `/api/cogents/{name}/channels` | GET | Channels list |
| `/api/cogents/{name}/channels/{id}` | GET | Channel detail with messages |
| `/api/cogents/{name}/schemas` | GET | Schema definitions |
| `/api/cogents/{name}/runs` | GET | Run history |
| `/api/cogents/{name}/runs/{id}` | GET | Run detail |
| `/api/cogents/{name}/runs/{id}/logs` | GET | Run CloudWatch logs |
| `/api/cogents/{name}/events` | GET | Events log |
| `/api/cogents/{name}/events/{id}/tree` | GET | Event causal tree |
| `/api/cogents/{name}/cron` | GET | Cron rules |
| `/api/cogents/{name}/cron/toggle` | POST | Toggle cron rule |
| `/api/cogents/{name}/resources` | GET | Active resources |
| `/api/cogents/{name}/setup` | GET | Channel setup wizard |
| `/ws/cogents/{name}` | WS | Real-time updates |

### Architecture

- **Backend**: FastAPI + RDS Data API, port 8100
- **Frontend**: Next.js 15 + React 19 + Tailwind v4, port 5174
- **Real-time**: WebSocket via PostgreSQL LISTEN/NOTIFY
- **Auth**: API key in `x-api-key` header (SHA-256 hashed, stored in Secrets Manager)

### Database Connection

Both the dashboard and `cogos` CLI require RDS Data API credentials (`DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`). Set `USE_LOCAL_DB=1` to use LocalRepository (JSON file at `~/.cogent/local/data.json`) for local dev without AWS.

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
