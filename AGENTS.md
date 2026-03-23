# CogOS — Autonomous Software Engineering Agent

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

All team communication happens on **Discord** (not Slack). When you see `#channel-name`, that refers to a Discord channel.

### Posting to Discord

Post announcements using `cogos.io.discord.announce`, which creates per-cogent webhooks (named `cogent-{username}`) so messages appear under the cogent's identity:

```bash
# Post as the current checkout's identity
PYTHONPATH=src python -m cogos.io.discord.announce \
  --channel-id 1475918657153663018 \
  --username "cogents.0" \
  --message "Pushed to main: ..."

# Or from Python
from cogos.io.discord.announce import post
post(channel_id="1475918657153663018", username="cogents.0", message="...")
```

The bot token is read from `COGOS_DISCORD_TOKEN` env var, falling back to `agora/discord` in AWS Secrets Manager.

Key channel IDs:
- `#cogents` — `1475918657153663018` (announcements, deploy summaries, status updates)

Discord messages have a 2000-character limit — split longer posts into multiple messages.

## Project Layout

```
src/
  cogtainer/    # Persistent state, DB, infrastructure (firmware)
  cogos/        # Execution engine (operating system)
  memory/       # Persistent memory (PostgreSQL)
  cogos/io/     # External IO (Discord, GitHub, Asana, email)
  cli/          # Main cogos CLI
  dashboard/    # Operational dashboard
  body/         # Agent runtime (ECS task)
  run/          # Run management CLI
docs/
  cogtainer/    # Cogtainer design and CLI reference
tests/
```

## Cogtainer — Infrastructure

A cogtainer is the self-contained environment (AWS, local, or Docker) that hosts cogents. It manages shared AWS resources: ECS cluster, ECR container registry, Route53 DNS, secrets, and monitoring.

**LLM config is always required.** `CogtainerEntry.llm` is non-optional for all cogtainer types (aws, local, docker). The CLI defaults to bedrock/claude-sonnet when no `--llm-*` flags are passed.

- **Design**: [docs/cogtainer/design.md](docs/cogtainer/design.md) — Architecture, module structure, resource details
- **CLI Reference**: [docs/cogtainer/cli.md](docs/cogtainer/cli.md) — All commands with examples and options

Key commands:

```bash
cogtainer status                 # Show infrastructure health
cogtainer status <name>          # Show a specific cogtainer's health
cogent list                      # All cogents with CPU/memory/channels
```

## AWS Infrastructure

Cogtainer infrastructure details (account IDs, ECR URL, domain, SSO profile) are configured in `~/.cogos/cogtainers.yml`. Use the CLI to discover them:

```bash
cogtainer status           # Show infrastructure details
cogent list                # Show all cogent instances
```

## Secret Path Conventions

```
cogent/{name}/{channel}    # Per-cogent channel creds (e.g., cogent/alpha/discord)
cogtainer/shared/{key}     # Org-wide shared keys (e.g., cogtainer/shared/jwt-signing-key)
```

## Running a Cogent Locally vs on AWS

Set `COGENT=local` to run on this machine using LocalRepository. The default data path is `~/.cogos/local/cogos_data.json`; source `dashboard/ports.sh` to use `.local/cogos/cogos_data.json` under the checkout instead. Set `COGOS_LOCAL_DATA` to override the path. Any other cogent name targets that cogent's AWS infrastructure (RDS, Lambda, ECS).

The `cogos` CLI reads the cogent name from the `COGENT` env var (with `COGTAINER` if multiple cogtainers are configured) or from `~/.cogos/cogtainers.yml`.

### Local: Run CogOS on this machine

Requires AWS credentials for Bedrock (LLM calls). No Lambda, no RDS, no EventBridge.

```bash
export COGENT=local

# 1. Boot an image into local DB and start dispatcher
cogos start --clean

# 2. (Optional) Start Discord bridge locally
cogos io discord run-local

# 3. Run a single process manually
cogos process run <process-name> --executor local

# 4. Check status
cogos status
cogos run list
```

### Validated Local Operations

All of the following work with `COGENT=local`:

| Operation | Command |
|-----------|---------|
| Boot image | `cogos start --clean` |
| Check status | `cogos status` |
| List capabilities | `cogos capability list` |
| Inspect capability | `cogos capability get <name>` |
| List/read/create files | `cogos file list`, `file get`, `file create` |
| List handlers | `cogos handler list` |
| Emit channel message | `cogos channel send <channel> --payload '{...}'` |
| Run process directly | `cogos process run <name> --executor local` |
| Disable process | `cogos process disable <name>` |
| View run history | `cogos run list`, `run show <id>` |
| Wipe all data | `cogos wipe -y` |
| Reload from image | `cogos reload -i cogos -y` |
| Discord IO help | `cogos io discord --help` |

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
# Background (recommended for dev, with COGENT=local):
cogos dashboard start             # local JSON DB, runs in background
cogos dashboard stop              # stop both servers
cogos dashboard reload            # restart (stop + start)
```

`cogos dashboard start` runs both backend and frontend in the background, tracking PIDs for clean stop/reload. Logs go to `/tmp/cogos-backend.log` and `/tmp/cogos-frontend.log`.

Manual (two terminals):
```bash
source dashboard/ports.sh
USE_LOCAL_DB=1 uv run uvicorn cogos.api.app:app --host 0.0.0.0 --port "$DASHBOARD_BE_PORT"
cd dashboard/frontend && npm run dev
```

## Remote Deployment and Testing

### Deploying a cogtainer (shared infrastructure)

A cogtainer manages shared resources (ECS cluster, ECR, Route53, DynamoDB, OIDC, secrets). Deploy via the `cogtainer` CLI:

```bash
cogtainer create <name> --type aws  # First-time: create cogtainer + deploy all CDK stacks
cogtainer update <name>             # Update CDK stacks with code changes
cogtainer status [<name>]           # Check infrastructure health
cogtainer destroy <name>            # Tear down (prompts for confirmation)
```

See [docs/cogtainer/cli.md](docs/cogtainer/cli.md) for full reference.

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
COGENT=<name> cogos cogtainer await                          # Wait for executor-<sha>
COGENT=<name> cogos cogtainer await --prefix dashboard       # Wait for dashboard-<sha>
COGENT=<name> cogos cogtainer await --tag dashboard-latest   # Wait for specific tag

# Deploy dashboard image to ECS
COGENT=<name> cogos cogtainer update ecs --tag dashboard-latest
COGENT=<name> cogos cogtainer update ecs --tag dashboard-abc1234

# Deploy executor code to Lambda (no Docker needed)
COGENT=<name> cogos cogtainer update lambda
```

Local builds (`cogtainer build`, `dashboard deploy --docker`) still work when needed.

### Deploying a cogent instance (decision tree)

See [docs/deploy.md](docs/deploy.md) for the full reference. Match what changed to the right command:

| What changed | Command |
|---|---|
| `images/**` only | `cogos restart` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**`, `src/cogos/capabilities/**` | `cogtainer update lambda` |
| `dashboard/frontend/**` only | CI builds automatically; then `cogtainer update dashboard` |
| `src/dashboard/**` (backend) | CI builds automatically; then `cogtainer update dashboard` |
| `src/cogtainer/docker/**` (Dockerfile/deps) | CI builds automatically; executor runs as Lambda, no ECS deploy needed |
| `dashboard/Dockerfile`, backend deps | CI builds automatically; then `cogtainer update dashboard` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogtainer update stack` |

Common sequences:

```bash
# Executor code change
cogtainer update lambda
cogos restart    # if image also changed

# Full infrastructure change (CDK constructs, IAM, ALB)
cogtainer update stack
cogos restart
```

### Managing the Discord bridge (remote)

```bash
COGENT=<name> cogos io discord start     # Scale ECS service to 1 task
COGENT=<name> cogos io discord stop      # Scale to 0
COGENT=<name> cogos io discord restart   # Force new deployment
COGENT=<name> cogos io discord status    # Check running/desired counts
```

### Testing a deployed dashboard

Use the `dashboard.test` skill which automates PAT-authenticated UI and API testing against the deployed dashboard. Or test manually with curl:

```bash
curl -H 'X-Api-Key: <pat>' https://<safe-name>.<your-domain>/api/cogents/<name>/status
```

## AWS Debugging — NEVER just wait and retry

When deploying to AWS, **actively diagnose failures**. Do not sleep/poll CloudFormation and hope it works. Follow this protocol:

### 1. Check CloudFormation events (not just status)

```python
from cogtainer.aws import get_aws_session, set_org_profile
set_org_profile()
session, _ = get_aws_session()
cf = session.client('cloudformation', region_name='us-east-1')

# Events show WHAT failed and WHY
resp = cf.describe_stack_events(StackName='cogtainer-agora-alpha')
for e in resp['StackEvents'][:10]:
    reason = e.get('ResourceStatusReason', '')
    if reason:
        print(f"{e['LogicalResourceId']}: {e['ResourceStatus']} - {reason[:150]}")
```

### 2. When ECS service won't stabilize, check the TASKS

Don't wait 40 minutes for CloudFormation timeout. Check immediately:

```python
ecs = session.client('ecs', region_name='us-east-1')

# Running tasks — are containers actually up?
running = ecs.list_tasks(cluster='cogtainer-agora', desiredStatus='RUNNING')

# Stopped tasks — WHY did they stop?
stopped = ecs.list_tasks(cluster='cogtainer-agora', desiredStatus='STOPPED', maxResults=3)
tasks = ecs.describe_tasks(cluster='cogtainer-agora', tasks=stopped['taskArns'])
for t in tasks['tasks']:
    print(f"StopCode: {t.get('stopCode')} Reason: {t.get('stoppedReason')}")
    for c in t['containers']:
        print(f"  {c['name']}: exit={c.get('exitCode')} reason={c.get('reason')}")
```

Common ECS failures:
- **`ResourceInitializationError: unable to pull`** → execution role missing ECR auth permissions
- **`EssentialContainerExited` exit=1** → container crashed, check CloudWatch logs
- **`Target.Timeout`** → health check port not exposed or wrong port in target group
- **`CannotPullContainerError`** → wrong image tag or ECR repo doesn't exist

### 3. Check CloudWatch logs for the actual container output

```python
logs = session.client('logs', region_name='us-east-1')
import time

# List log groups to find the right one
resp = logs.describe_log_groups(logGroupNamePrefix='cogtainer-agora-alpha')
for lg in resp['logGroups']:
    print(lg['logGroupName'])

# Get recent logs
resp = logs.filter_log_events(
    logGroupName='<log-group-name>',
    startTime=int((time.time() - 300) * 1000),  # last 5 min
    limit=30,
)
for e in resp['events']:
    print(e['message'].strip())
```

### 4. Check ALB target group health

```python
elbv2 = session.client('elbv2', region_name='us-east-1')
resp = elbv2.describe_target_groups()
for tg in resp['TargetGroups']:
    if 'cogtai' in tg['TargetGroupName']:
        health = elbv2.describe_target_health(TargetGroupArn=tg['TargetGroupArn'])
        for t in health['TargetHealthDescriptions']:
            state = t['TargetHealth']['State']
            desc = t['TargetHealth'].get('Description', '')
            print(f"{tg['TargetGroupName']}: {state} {desc}")
```

### 5. Cancel stuck deploys instead of waiting

```python
cf.cancel_update_stack(StackName='cogtainer-agora-alpha')
```

### Key rules

- **NEVER `sleep 120` and check status.** Check ECS tasks, logs, and target health IMMEDIATELY.
- **NEVER retry a deploy without understanding why it failed.** Read the logs first.
- **If a container exits with code 1**, the answer is in CloudWatch logs, not in CloudFormation events.
- **If health checks fail**, check: (a) is the container actually running? (b) is the correct port exposed? (c) does the security group allow traffic?
- **If ECR pull fails**, the execution role needs `ecr:GetAuthorizationToken` + `ecr:BatchGetImage` on `Resource: "*"`.

## Dashboard Testing with agent-browser

Use the `agent-browser` skill to test the CogOS Dashboard interactively.

### Prerequisites

Start the dashboard:

```bash
COGENT=local cogos dashboard start
```

Or manually:

```bash
source dashboard/ports.sh
USE_LOCAL_DB=1 uv run uvicorn cogos.api.app:app --host 0.0.0.0 --port "$DASHBOARD_BE_PORT" --reload
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
| Configure | Setup, Integrations, and Capabilities sub-tabs | Switch sub-tabs, click rows for detail |
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

Both the dashboard and `cogos` CLI require RDS Data API credentials (`DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`). Set `USE_LOCAL_DB=1` to use LocalRepository for local dev without AWS. The default local data path is `~/.cogos/local/cogos_data.json`; source `dashboard/ports.sh` to use `.local/cogos/` under the checkout instead, or set `COGOS_LOCAL_DATA` to override.

## Development

When starting a new task with a clean repo, always pull latest first:

```bash
git pull origin main          # Sync with remote before starting work
uv sync --all-extras          # Install dependencies
uv run pytest                 # Run tests
uv run cogtainer status       # Check infrastructure
```

### Verification After Code Changes

After making code changes, always run pyright and tests before considering the task complete:

```bash
uv run pyright                # Type-check — must pass with zero errors
uv run pytest tests/ -q       # Unit tests — must pass
```

Do NOT push, commit, or claim work is done until both pass cleanly. If either fails, fix the issues first.

### Remote / Headless Sessions

When running as a remote Claude Code session (dispatched from desktop or mobile), run `/sandbox.up` at the start of the session before testing any code changes. This idempotently ensures:

- Dependencies are installed (`uv sync`)
- A local cogtainer and cogent exist
- The cogent selection is persisted to `.env`
- The dispatcher is running with the latest code

For full end-to-end verification (diagnostics + dashboard), use `/sandbox.local-test` instead.

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
