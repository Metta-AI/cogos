# Cogent — Autonomous Software Engineering Agent

Built on the Viable System Model. Each cogent is an autonomous agent with its own ECS task, database, and channel integrations.

## Project Layout

```
src/
  body/         # Agent runtime (ECS task)
  brain/        # LLM reasoning engine
  mind/         # Agent personality and goals
  memory/       # Persistent memory (PostgreSQL)
  channels/     # External integrations (Discord, GitHub, Gmail, Asana, Calendar)
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
agent-browser open http://localhost:5174 && agent-browser wait --load networkidle && agent-browser snapshot -i
```

### Dashboard Panels to Test

The dashboard has 10 tabs accessible via the sidebar:

| Tab | Description | Key interactions |
|-----|-------------|-----------------|
| Overview | Stat cards, recent events, top programs | Verify stat rendering |
| Programs | Program table with expandable executions | Click rows to expand execution detail |
| Sessions | Session list with execution stats | Sort columns, verify data |
| Events | Event log with expandable payloads | Expand events, click tree view button |
| Triggers | Grouped triggers with toggle switches | Toggle switches on/off |
| Memory | Scoped memory browser | Expand/collapse groups |
| Resources | Active sessions with stat cards | Verify stat cards |
| Tasks | Task queue with expandable detail | Expand task rows |
| Channels | Channel registry table | Click for channel detail |
| Alerts | Alert list with severity badges | Check badge colors by severity |

### Testing Workflow

```bash
# Open dashboard and orient
agent-browser open http://localhost:5174
agent-browser wait --load networkidle
agent-browser snapshot -i

# Click through each sidebar tab
agent-browser click @e{N}  # Use ref from snapshot for sidebar tab
agent-browser wait --load networkidle
agent-browser snapshot -i

# Test interactive elements (expand rows, toggle switches, etc.)
agent-browser click @e{N}
agent-browser snapshot -i

# Check for console errors
agent-browser console

# Take annotated screenshots for visual review
agent-browser screenshot --annotate ./test-output/dashboard.png
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

- **Backend**: FastAPI + asyncpg (PostgreSQL), port 8100
- **Frontend**: Next.js 15 + React 19 + Tailwind v4, port 5174
- **Real-time**: WebSocket via PostgreSQL LISTEN/NOTIFY
- **Auth**: API key in `x-api-key` header (SHA-256 hashed, stored in Secrets Manager)

## Development

```bash
uv sync --all-extras          # Install dependencies
uv run pytest                 # Run tests
uv run polis status           # Check infrastructure
```
