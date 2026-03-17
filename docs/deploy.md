# Deploy Guide

Single reference for deploying Cogent components. For operational runbooks used by Claude, see `.claude/commands/deploy.*.md`.

## Architecture

Four deployable components:

| Component | Infrastructure | Deploy tool |
|-----------|---------------|-------------|
| **Lambda functions** | orchestrator, executor, dispatcher, ingress | `cogtainer update lambda` |
| **Database schema** | Aurora PostgreSQL via RDS Data API | `cogtainer update rds` |
| **Dashboard** | ECS Fargate on cogent-polis cluster | `dashboard deploy` |
| **CDK stack** | All infrastructure definitions (IAM, VPC, ALB, ECS task defs) | `cogtainer create --watch` |

## Decision Tree

What changed? Run `git diff HEAD~1 --name-only` and match:

| Changed paths | Command |
|---|---|
| `images/**` | `cogent <name> cogos image boot cogent-v1` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**` | `cogent <name> cogtainer update lambda` |
| `src/cogos/capabilities/**` | `cogent <name> cogtainer update lambda` + `cogos image boot cogent-v1` |
| `src/cogos/db/migrations/**` | `cogent <name> cogtainer update rds` |
| `dashboard/frontend/**` | `cogent <name> dashboard deploy` |
| `src/dashboard/**` | `cogent <name> dashboard deploy --docker` |
| Both frontend + backend | `cogent <name> dashboard deploy --docker` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogent <name> cogtainer create --watch` |
| `DOCKER_VERSION` changed | `cogent <name> cogtainer create --watch` |

## Command Reference

### Lambda + DB

```bash
cogent <name> cogtainer update lambda       # Update Lambda code only (~15s)
cogent <name> cogtainer update rds          # Run DB schema migrations
cogent <name> cogtainer update ecs          # Force new ECS deployment (restart containers)
cogent <name> cogtainer update all          # Lambda + RDS migrations + sync
```

### CDK Stack

```bash
cogent <name> cogtainer create --watch      # Full CDK deploy (~3-5 min)
cogent <name> cogtainer build               # Build + push executor Docker image to ECR
cogent <name> cogtainer status              # Check infrastructure status
```

### Image

```bash
cogent <name> cogos image boot cogent-v1          # Upsert capabilities, files, processes into DB
cogent <name> cogos image boot cogent-v1 --clean  # Wipe all tables first, then boot
cogent <name> cogos reload -i cogent-v1 -y        # Reload config from image, preserving runtime data
cogent <name> cogos reload -i cogent-v1 -y --full # Wipe ALL data (including runtime) and reload
```

### Dashboard

```bash
cogent <name> dashboard deploy              # Fast path: Next.js build -> S3 -> restart ECS (~30s)
cogent <name> dashboard deploy --docker     # Full path: rebuild Docker image + push ECR + restart
cogent <name> dashboard deploy --skip-health  # Skip health check wait
cogent <name> cogos dashboard reload          # Restart local dashboard (stop + start)
```

### Discord Bridge

```bash
cogent <name> cogos io discord start        # Scale ECS service to 1 task
cogent <name> cogos io discord stop         # Scale to 0
cogent <name> cogos io discord restart      # Force new deployment
cogent <name> cogos io discord status       # Check running/desired counts
```

## Typical Sequences

**Image-only change** (edited files in `images/`):
```bash
cogent <name> cogos image boot cogent-v1
```

**Executor code change** (`src/cogos/executor/`, `src/cogos/sandbox/`):
```bash
cogent <name> cogtainer update lambda
cogent <name> cogos image boot cogent-v1    # if image also changed
```

**Schema migration + executor change**:
```bash
cogent <name> cogtainer update rds
cogent <name> cogtainer update lambda
cogent <name> cogos image boot cogent-v1
```

**Dashboard frontend-only**:
```bash
cogent <name> dashboard deploy
```

**Dashboard with backend changes**:
```bash
cogent <name> dashboard deploy --docker
```

**Full infrastructure change** (CDK constructs, IAM, ALB):
```bash
cogent <name> cogtainer create --watch
cogent <name> cogos image boot cogent-v1
```

**Docker image change** (Dockerfile, new deps):
```bash
cogent <name> cogtainer build
cogent <name> cogtainer update ecs
```

## Post-Deploy Verification

```bash
cogent <name> cogtainer status              # Infrastructure health
cogent <name> cogos status                  # CogOS status
cogent <name> cogos process list            # Processes running
```

For dashboard, open `https://<safe-name>.softmax-cogents.com` and confirm the change is visible.
