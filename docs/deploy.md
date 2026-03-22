# Deploy Guide

Single reference for deploying CogOS components. For operational runbooks used by Claude, see `.claude/commands/deploy.*.md`.

## Architecture

Four deployable components:

| Component | Infrastructure | Deploy tool |
|-----------|---------------|-------------|
| **Lambda functions** | event-router, executor, dispatcher, ingress | `cogtainer update lambda` |
| **Dashboard / ECS** | ECS Fargate on cogtainer cluster | `cogtainer update dashboard` |
| **Discord bridge** | ECS Fargate on cogtainer cluster | `cogtainer update discord` |
| **CDK stack** | All infrastructure definitions (IAM, VPC, ALB, ECS task defs) | `cogtainer update stack` |

## Decision Tree

What changed? Run `git diff HEAD~1 --name-only` and match:

| Changed paths | Command |
|---|---|
| `images/**` | `cogos restart` |
| `src/cogos/executor/**`, `src/cogos/sandbox/**` | `cogtainer update lambda` |
| `src/cogos/capabilities/**` | `cogtainer update lambda` + `cogos restart` |
| `dashboard/frontend/**` | CI builds automatically; then `cogtainer update dashboard` |
| `src/dashboard/**` | CI builds automatically; then `cogtainer update dashboard` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | `cogtainer update stack` |

## Command Reference

### Update all components

```bash
cogtainer update                             # Update all: Lambda + RDS + dashboard + discord bridge
cogtainer update lambda                      # Update Lambda code only
cogtainer update dashboard                   # Update dashboard (frontend + ECS)
cogtainer update discord                     # Update discord bridge ECS service
cogtainer update rds                         # Run DB migrations
cogtainer update ecs --tag dashboard-<sha>   # Deploy specific ECS image
```

### Start / Stop / Restart

```bash
cogos start                     # Boot image + start dispatcher
cogos start --clean             # Wipe all tables first, then boot + start
cogos start --skip-boot         # Start dispatcher without re-booting image
cogos stop                      # Stop dispatcher
cogos restart                   # Stop + boot + start
cogos snapshot my-snapshot      # Snapshot running state into an image
```

### Dashboard (local)

```bash
cogos dashboard start             # Start backend + frontend in background (local dev)
cogos dashboard stop              # Stop both servers
cogos dashboard reload            # Restart (stop + start)
```

### Discord Bridge

```bash
cogos io discord start        # Scale ECS service to 1 task
cogos io discord stop         # Scale to 0
cogos io discord restart      # Force new deployment
cogos io discord status       # Check running/desired counts
```

## Typical Sequences

**Image-only change** (edited files in `images/`):
```bash
cogos restart
```

**Executor code change** (`src/cogos/executor/`, `src/cogos/sandbox/`):
```bash
cogtainer update lambda
cogos restart    # if image also changed
```

**Full infrastructure change** (CDK constructs, IAM, ALB):
```bash
cogtainer update stack
cogos restart
```

## Post-Deploy Verification

```bash
cogtainer status                              # Infrastructure health
cogos status                                  # CogOS status
cogos process list                            # Processes running
```

For dashboard, open `https://<safe-name>.<your-domain>` and confirm the change is visible.
