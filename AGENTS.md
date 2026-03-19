# Cogent — Autonomous Software Engineering Agent

Built on the Viable System Model. Each cogent is an autonomous agent with its own ECS task, database, and channel integrations.

## Glossary

| Term | Definition |
|------|-----------|
| **Cogent** | An autonomous agent instance. Has its own database, channels, identity, and set of cogs. The top-level entity. |
| **Cogtainer** | The infrastructure container that hosts a cogent — ECS task, RDS database, Lambda functions, and IAM roles. One cogtainer per cogent. |
| **Cog** | A functional module within a cogent (e.g. `discord`, `supervisor`, `worker`). Creates coglets given a context. Has a default coglet that runs on cog startup. |
| **Coglet** | The unit of work. Processes input/events and produces output/logs. Has a parent cog. Can be run via CogletRuntime, which creates a process for it. |
| **CogletRuntime** | The execution layer that runs coglets — spawns processes from cog and coglet manifests with scoped capabilities. |

## Communication

All team communication happens on **Discord** (not Slack). When you see `#channel-name`, that refers to a Discord channel. Post updates using the Discord webhook stored in AWS Secrets Manager:

```bash
# Webhook secrets are at discord/channel-webhook/{channel} or discord/agent-webhook-url
aws secretsmanager get-secret-value --secret-id "discord/agent-webhook-url" --query SecretString --output text

# Post as a cogent identity:
curl -X POST "$WEBHOOK_URL" -H "Content-Type: application/json" \
  -d '{"username": "<name>", "content": "message here"}'
```

Discord messages have a 2000-character limit — split longer posts into multiple messages.

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

Polis infrastructure details (account IDs, ECR URL, domain, SSO profile) are configured in `~/.cogos/config.yml` with fallbacks in `src/polis/config.py`. Use the CLI to discover them:

```bash
polis status        # Show infrastructure details
polis cogents list  # Show all cogent instances
```

## Secret Path Conventions

```
cogent/{name}/{channel}    # Per-cogent channel creds (e.g., cogent/alpha/discord)
polis/shared/{key}         # Org-wide shared keys (e.g., polis/shared/jwt-signing-key)
```

## Running a Cogent Locally vs on AWS

`cogent local ...` (or `cogos -c local ...`) means run on this machine using LocalRepository. By default, each checkout gets its own local JSON store at `.local/cogos/cogos_data.json` under that repo. Set `COGENT_LOCAL_DATA` to override it. Any other cogent name targets that cogent's AWS infrastructure (RDS, Lambda, ECS).

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
| Emit channel message | `cogent local cogos channel send <channel> --payload '{...}'` |
| Run executor tick | `cogent local cogos run-local --once` |
| Run process directly | `cogent local cogos process run <name> --local` |
| Disable process | `cogent local cogos process disable <name>` |
| View run history | `cogent local cogos run list`, `run show <id>` |
| Wipe all data | `cogent local cogos wipe -y` |
| Reload from image | `cogent local cogos reload -i cogent-v1 -y` |
| Discord IO help | `cogent local cogos io discord --help` |

Validation checklist with step-by-step commands: `tests/cogos/local_validation.md`

## Dashboard Ports

Dashboard ports can be pinned in the repo root `.env` file:

```
DASHBOARD_BE_PORT=8100    # FastAPI backend
DASHBOARD_FE_PORT=5200    # Next.js frontend dev server
```

If `.env` does not set them, the CLI and `dashboard/ports.sh` derive a stable backend/frontend port pair from the checkout path so multiple clones can run side by side without port collisions.

In dev mode, the Next.js frontend proxies `/api/*` and `/ws/*` to the backend via `rewrites` in `next.config.ts`. You access the app at the **frontend port** (for example the derived value or the one in `.env`), and it forwards API calls to the backend port transparently.

In production (Docker), both are served on a single port (8100) — Next.js is statically exported and served by FastAPI.

### Starting the dashboard

```bash
# Background (recommended for dev):
cogent local cogos dashboard start             # local JSON DB, runs in background
cogent local cogos dashboard stop              # stop both servers
cogent local cogos dashboard reload            # restart (stop + start)

# Foreground (opens browser):
cogent local dashboard serve --db local        # local JSON DB
cogent <name> dashboard serve --db prod          # live polis DB
```

`cogos dashboard start` runs both backend and frontend in the background, tracking PIDs for clean stop/reload. Logs go to `/tmp/cogent-backend.log` and `/tmp/cogent-frontend.log`.

# Manual (two terminals):
source dashboard/ports.sh
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port "$DASHBOARD_BE_PORT"
cd dashboard/frontend && npm run dev
```

`--db local` sets `USE_LOCAL_DB=1` and defaults `COGENT_LOCAL_DATA` to this checkout's `.local/cogos` directory. `--db prod` assumes into the polis account to get live RDS credentials.

## Remote Deployment and Testing

### Deploying polis (shared infrastructure)

Polis manages shared resources (ECS cluster, ECR, Route53, DynamoDB, OIDC, secrets). Deploy via the `polis` CLI, **not** `cogtainer`:

```bash
polis create                    # First-time: create polis account + deploy all CDK stacks
polis update                    # Update CDK stacks with code changes
polis status                    # Check infrastructure health
polis destroy                   # Tear down (prompts for confirmation)
```

The CDK app is at `src/polis/cdk/app.py` and deploys two stacks:
- `cogent-polis` — ECS cluster, ECR repo, Route53, DynamoDB, watcher Lambda, GitHub Actions OIDC
- `cogent-secrets` — Rotation Lambda, cross-account SecretsReaderRole

See [docs/polis/cli.md](docs/polis/cli.md) for full reference.

### CI Docker builds (GitHub Actions)

Docker images are built automatically by GitHub Actions on push to main when relevant files change. No local Docker builds needed for routine deploys.

| Image | Trigger paths | Tag format |
|-------|--------------|------------|
| Executor | `src/cogtainer/docker/**`, `src/cogos/**`, `src/cogents/**`, `pyproject.toml` | `executor-{sha}`, `executor-latest` |
| Dashboard | `dashboard/**`, `src/dashboard/**` | `dashboard-{sha}`, `dashboard-latest` |

Workflows can also be triggered manually via `gh workflow run`.

All `cogtainer update` commands check that a CI-built ECR image exists for the current commit and warn if it doesn't. Use `cogtainer await` to wait for CI before deploying.

**Executor** images run as Lambda (not ECS). **Dashboard** images run as ECS. Don't mix them up — `update ecs --tag executor-*` is rejected with an error.

```bash
# Wait for CI to finish building
cogent <name> cogtainer await                          # Wait for executor-<sha>
cogent <name> cogtainer await --prefix dashboard       # Wait for dashboard-<sha>
cogent <name> cogtainer await --tag dashboard-latest   # Wait for specific tag

# Deploy dashboard image to ECS
cogent <name> cogtainer update ecs --tag dashboard-latest
cogent <name> cogtainer update ecs --tag dashboard-abc1234

# Deploy executor code to Lambda (no Docker needed)
cogent <name> cogtainer update lambda
```

Local builds (`cogtainer build`, `dashboard deploy --docker`) still work when needed.

### Deploying a cogent (decision tree)

See [docs/deploy.md](docs/deploy.md) for the full reference. Match what changed to the right command:

| What changed | Command |
|---|---|
| `images/**` only | `cogent <name> cogos image boot cogent-v1` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**`, `src/cogos/capabilities/**` | `cogent <name> cogtainer update lambda` |
| `src/cogos/db/migrations/**` | `cogent <name> cogtainer update rds` |
| `dashboard/frontend/**` only | `cogent <name> dashboard deploy` |
| `src/dashboard/**` (backend) | `cogent <name> dashboard deploy --docker` |
| `src/cogtainer/docker/**` (Dockerfile/deps) | CI builds automatically; executor runs as Lambda, no ECS deploy needed |
| `dashboard/Dockerfile`, backend deps | CI builds automatically; then `cogent <name> cogtainer update ecs --tag dashboard-latest` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogent <name> cogtainer create` |

Common sequences:

```bash
# Executor code change
cogent <name> cogtainer update lambda
cogent <name> cogos image boot cogent-v1    # if image also changed

# Schema migration + executor change
cogent <name> cogtainer update rds
cogent <name> cogtainer update lambda

# Full infrastructure change (CDK constructs, IAM, ALB)
cogent <name> cogtainer create
cogent <name> cogos image boot cogent-v1
```

### Managing the Discord bridge (remote)

```bash
cogent <name> cogos io discord start     # Scale ECS service to 1 task
cogent <name> cogos io discord stop      # Scale to 0
cogent <name> cogos io discord restart   # Force new deployment
cogent <name> cogos io discord status    # Check running/desired counts
```

### Testing a deployed dashboard

1. Create a PAT (Personal Access Token) for API access:

```bash
cogent <name> dashboard create-pat
cogent <name> cogtainer create              # Apply ALB bypass rule
```

2. Test with curl:

```bash
curl -H 'X-Api-Key: <pat>' https://<safe-name>.<your-domain>/api/cogents/<name>/status
```

3. Or use the `dashboard.test` skill which automates PAT-authenticated UI and API testing against the deployed dashboard.

## Dashboard Testing with agent-browser

Use the `agent-browser` skill to test the Cogent Dashboard interactively.

### Prerequisites

Start the dashboard:

```bash
cogent local cogos dashboard start
```

Or manually:

```bash
source dashboard/ports.sh
USE_LOCAL_DB=1 uv run uvicorn dashboard.app:app --host 0.0.0.0 --port "$DASHBOARD_BE_PORT" --reload
cd dashboard/frontend && npm run dev
```

### Quick Start

```bash
source dashboard/ports.sh
npx agent-browser open "http://localhost:$DASHBOARD_FE_PORT" && npx agent-browser wait --load networkidle && npx agent-browser snapshot -i
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
source dashboard/ports.sh
npx agent-browser open "http://localhost:$DASHBOARD_FE_PORT"
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
/dogfood http://localhost:<frontend-port>
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

- **Backend**: FastAPI + RDS Data API, checkout-derived dev port unless overridden
- **Frontend**: Next.js 15 + React 19 + Tailwind v4, checkout-derived dev port unless overridden
- **Real-time**: WebSocket via PostgreSQL LISTEN/NOTIFY
- **Auth**: API key in `x-api-key` header (SHA-256 hashed, stored in Secrets Manager)

### Database Connection

Both the dashboard and `cogos` CLI require RDS Data API credentials (`DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`). Set `USE_LOCAL_DB=1` to use LocalRepository for local dev without AWS. The CLI defaults local state to `.local/cogos/cogos_data.json` in the current checkout unless `COGENT_LOCAL_DATA` is set.

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
