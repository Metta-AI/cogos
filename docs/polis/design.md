# Polis Design

Polis is the shared infrastructure hub for all cogents in an AWS Organization.
It provisions shared resources, manages credentials, and monitors cogent health.

## Architecture

Three layers:

1. **Infrastructure** (CDK) — Shared AWS resources: ECS cluster, ECR repo,
   Route53 hosted zone, DynamoDB status table, watcher Lambda.
2. **Secrets** — AWS Secrets Manager as centralized credential store. Agents
   fetch keys directly via IAM task roles. Rotation handled by Lambda.
3. **Monitoring** — EventBridge-triggered Lambda polls CF/ECS/CloudWatch every
   60s, writes aggregated status to DynamoDB. CLI reads from DynamoDB.

### What changed from the original polis

- No Envoy sidecar or auth injector proxy
- No WebSocket proxy or boundary stack
- No Python-generated CloudFormation — replaced by CDK
- Agents access secrets directly instead of going through a proxy

## Module Structure

```
src/polis/
  __init__.py
  cli.py              # Click CLI
  config.py            # PolisConfig model
  aws.py               # AWS session/account helpers
  cdk/
    app.py             # CDK app entry point
    stacks/
      core.py          # ECS, ECR, Route53, DynamoDB, watcher Lambda
      secrets.py       # Secrets Manager resources, rotation Lambda
  secrets/
    store.py           # SecretStore client
    rotation/
      handler.py       # Rotation Lambda handler
  watcher/
    handler.py         # Agent watcher Lambda handler
```

## Infrastructure Layer (CDK)

A single `PolisStack` with these resources:

### ECS Cluster (`cogent-polis`)

- Capacity providers: FARGATE + FARGATE_SPOT
- Shared cluster where all cogent tasks run

### ECR Repository (`cogent`)

- Single repo, cogent name as tag prefix (e.g., `cogent:alpha-latest`,
  `cogent:beta-v1.2`)
- Cross-account pull policy scoped to the AWS Organization via
  `aws:PrincipalOrgID`
- Lifecycle policy to expire untagged images after 30 days

### Route53 Hosted Zone

- Domain for cogent DNS (configured via `deploy_config`)
- Cogent accounts create subdomains via cross-account delegation

### DynamoDB Table (`cogent-status`)

- Partition key: `cogent_name`
- Stores cached status: stack state, task counts, CPU/memory, channels,
  timestamp
- TTL on items to auto-expire stale entries

### Agent Watcher Lambda (`cogent-watcher`)

- Triggered by EventBridge rule every 60 seconds
- Queries all `cogent-*` CF stacks across the org
- Polls ECS for task counts, CloudWatch for CPU/memory metrics
- Writes aggregated status to DynamoDB

### IAM Roles

- Watcher Lambda execution role: CF describe, ECS list, CloudWatch get-metrics,
  DynamoDB write
- Cross-account role for cogent accounts to read from ECR and Secrets Manager

## Secrets Layer

AWS Secrets Manager as the centralized credential store. No proxies — agents
fetch keys directly using their IAM task role.

### Secret path convention

```
cogent/{cogent_name}/{channel}       # e.g., cogent/alpha/discord
cogent/{cogent_name}/{channel}/meta  # optional metadata
polis/shared/{key_name}              # org-wide shared keys
```

### SecretStore client (`secrets/store.py`)

Thin wrapper around boto3 Secrets Manager:

- `get(path) -> dict` — fetch and parse secret value
- `put(path, value)` — create or update a secret
- `list(prefix) -> list[str]` — list secret names under a prefix
- `delete(path)` — delete a secret
- In-memory TTL cache (5 min default) to avoid repeated API calls

### Access control

- Each cogent's ECS task role gets read access scoped to `cogent/{name}/*`
- Polis admin role gets full read/write
- Cross-account access via `aws:PrincipalOrgID` condition

### Rotation Lambda (`secrets/rotation/handler.py`)

Implements the Secrets Manager 4-step rotation protocol:

1. `createSecret` — generate new token
2. `setSecret` — store pending token
3. `testSecret` — verify pending token works
4. `finishSecret` — promote pending to current

Supported token types:
- **GitHub App** — generates RS256 JWT, creates installation access token
- **OAuth** — standard refresh_token flow

### CLI commands

```
polis secrets list [--cogent NAME]
polis secrets get <path>
polis secrets set <path> [--value | --file]
polis secrets delete <path>
polis secrets rotate <path>
```

## Monitoring Layer

### Agent Watcher Lambda

EventBridge triggers every 60s. The watcher:

1. Lists all `cogent-*` CloudFormation stacks in the org
2. Queries ECS for running/desired task counts per cogent
3. Queries CloudWatch for CPU (1m, 10m averages) and memory utilization
4. Checks Secrets Manager for channel token freshness
5. Writes a status record per cogent to DynamoDB

### DynamoDB status record

```
cogent_name: str       # partition key
stack_status: str      # e.g., CREATE_COMPLETE
running_count: int
desired_count: int
image_tag: str         # e.g., alpha-v1.3
channels: dict         # e.g., {"discord": "ok", "github": "stale"}
cpu_1m: int
cpu_10m: int
mem_pct: int
updated_at: int        # unix timestamp
```

## CLI

Entry point: `polis` (defined in pyproject.toml as `polis.cli:polis`).

### Commands

```
polis create                  # Create polis account + deploy CDK stack
polis update                  # Update CDK stack
polis destroy                 # Tear down CDK stack
polis status                  # Show polis resource status

polis secrets list [--cogent] # List secrets
polis secrets get <path>      # Get a secret value
polis secrets set <path>      # Set a secret
polis secrets delete <path>   # Delete a secret
polis secrets rotate <path>   # Trigger rotation

polis cogents list            # List all cogents with DynamoDB status
polis cogents status <name>   # Detailed status for one cogent
```

## Configuration

```python
class CogentMeta(BaseModel):
    description: str
    personality: str | None = None

class PolisConfig(BaseModel):
    name: str              # e.g., "my-polis"
    organization: str      # e.g., "MyOrg"
    owner: str
    domain: str            # e.g., "my-cogents.com"
    cogents: dict[str, CogentMeta]
```

Stored as YAML in the polis account's configuration.
