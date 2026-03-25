Deploy cogtainer infrastructure changes (CDK stack, Lambda, ECS).

Human-readable reference: [docs/deploy.md](../../docs/deploy.md)

This is the heaviest deploy — only use when actual infrastructure changes are needed.

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Ensure the right cogent is selected: check `.env` for COGTAINER/COGENT, or run `cogent select <name>` to set them. Verify with `cogos status`.

## Check: do you actually need a cogtainer deploy?

Run `git diff HEAD~1 --name-only` and check:

| Changed paths | Action |
|---|---|
| `src/cogtainer/cdk/**`, `DOCKER_VERSION`, IAM, VPC, ALB changes | **This skill** — read on |
| `images/**`, `src/cogos/**` | **Wrong skill** — use `/deploy.cogos` |
| `dashboard/**`, `src/dashboard/**` | **Wrong skill** — use `/deploy.dashboard` |

See [docs/deploy.md](../../docs/deploy.md) for the full decision tree. If the change doesn't require a cogtainer deploy, tell the user and suggest the right skill.

## Commands reference

### Per-cogent deploys (recommended)

```bash
# Per-cogent CDK stack update
cogent update stack

# Update Lambda code
cogent update lambda

# Deploy dashboard
cogent update dashboard

# Update all components
cogent update all
```

### Shared cogtainer infra (affects all cogents)

```bash
# Full CDK stack deploy (creates/updates all infra: VPC, ALB, Aurora cluster, etc.)
# This is slow (~3-5 min). Only use when shared infra changed.
cogtainer update <cogtainer-name>

# Update Lambda code for all cogents
cogtainer update <cogtainer-name> --lambdas

# Force new ECS deployment
cogtainer update <cogtainer-name> --services

# Deploy specific image to ECS
cogtainer update <cogtainer-name> --services --image-tag <tag>

# Check current infrastructure status
cogtainer status <cogtainer-name>
```

## When to use what

- **`cogent update stack`**: Per-cogent CDK changes — IAM, Lambda config, ECS task def changes for a single cogent.
- **`cogent update lambda`**: Only Python code in `src/cogos/` changed. Zips and uploads to existing Lambda.
- **`cogent update dashboard`**: Deploy a new dashboard version to ECS.
- **`cogtainer update <name>`** (no flags): Shared infra changes — VPC, ALB, Aurora cluster. This is the full deploy.
- **`cogtainer update <name> --services`**: Need to restart ECS tasks (e.g. after ECR image push).
- **Migrations**: DB migrations run automatically during image boot (`cogos start`), or manually via `cogent update rds`.

## Post-deploy

```bash
cogtainer status <cogtainer-name>
cogos status
```
