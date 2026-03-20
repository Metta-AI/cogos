# Deploy Guide

Single reference for deploying CogOS components. For operational runbooks used by Claude, see `.claude/commands/deploy.*.md`.

## Architecture

Four deployable components:

| Component | Infrastructure | Deploy tool |
|-----------|---------------|-------------|
| **Lambda functions** | event-router, executor, dispatcher, ingress | `cogtainer update <name> --lambdas` |
| **Dashboard / ECS** | ECS Fargate on cogtainer cluster | `cogtainer update <name> --services` |
| **CDK stack** | All infrastructure definitions (IAM, VPC, ALB, ECS task defs) | `cogtainer create <name> --type aws` |

## Decision Tree

What changed? Run `git diff HEAD~1 --name-only` and match:

| Changed paths | Command |
|---|---|
| `images/**` | `COGENT=<name> cogos image boot cogos` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**` | `cogtainer update <name> --lambdas` |
| `src/cogos/capabilities/**` | `cogtainer update <name> --lambdas` + `COGENT=<name> cogos image boot cogos` |
| `dashboard/frontend/**` | CI builds automatically; then `cogtainer update <name> --services --image-tag dashboard-latest` |
| `src/dashboard/**` | CI builds automatically; then `cogtainer update <name> --services --image-tag dashboard-latest` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogtainer create <name> --type aws` |

## Command Reference

### Lambda

```bash
cogtainer update <name> --lambdas          # Update Lambda code only
cogtainer update <name> --services         # Restart ECS services with new image
cogtainer update <name> --all              # Update both (default if no flags given)
```

Options: `--lambda-s3-bucket`, `--lambda-s3-key`, `--image-tag`, `--region`, `--profile`.

### Image

```bash
COGENT=<name> cogos image boot cogos          # Upsert capabilities, files, processes into DB
COGENT=<name> cogos image boot cogos --clean  # Wipe all tables first, then boot
COGENT=<name> cogos reload -i cogos -y        # Reload config from image, preserving runtime data
COGENT=<name> cogos reload -i cogos -y --full # Wipe ALL data (including runtime) and reload
```

### Dashboard (local)

```bash
cogos dashboard start             # Start backend + frontend in background (local dev)
cogos dashboard stop              # Stop both servers
cogos dashboard reload            # Restart (stop + start)
```

### Discord Bridge

```bash
COGENT=<name> cogos io discord start        # Scale ECS service to 1 task
COGENT=<name> cogos io discord stop         # Scale to 0
COGENT=<name> cogos io discord restart      # Force new deployment
COGENT=<name> cogos io discord status       # Check running/desired counts
```

## Typical Sequences

**Image-only change** (edited files in `images/`):
```bash
COGENT=<name> cogos image boot cogos
```

**Executor code change** (`src/cogos/executor/`, `src/cogos/sandbox/`):
```bash
cogtainer update <name> --lambdas
COGENT=<name> cogos image boot cogos    # if image also changed
```

**Full infrastructure change** (CDK constructs, IAM, ALB):
```bash
cogtainer create <name> --type aws
COGENT=<name> cogos image boot cogos
```

## Post-Deploy Verification

```bash
cogtainer status <name>                   # Infrastructure health
COGENT=<name> cogos status                # CogOS status
COGENT=<name> cogos process list          # Processes running
```

For dashboard, open `https://<safe-name>.<your-domain>` and confirm the change is visible.
