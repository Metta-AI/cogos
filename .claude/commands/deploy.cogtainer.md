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

```bash
# Full CDK stack deploy (creates/updates all infra: Lambda, ECS, ALB, etc.)
# This is slow (~3-5 min). Only use when infra definition changed.
cogtainer update <cogtainer-name>

# Update Lambda code only (fast, ~15s)
cogtainer update <cogtainer-name> --lambdas

# Deploy Lambda from local source
cogtainer update <cogtainer-name> --from-source

# Force new ECS deployment (restart containers with current image)
cogtainer update <cogtainer-name> --services

# Deploy specific image to ECS
cogtainer update <cogtainer-name> --services --image-tag <tag>

# Check current infrastructure status
cogtainer status <cogtainer-name>

# CogOS commands (resolve cogent from .env)
cogos status
cogos restart
```

## When to use what

- **`cogtainer update <name>`** (no flags): CDK stack changes — new resources, IAM policy changes, ALB rules, ECS task def changes, env var changes in CDK. This is the full deploy.
- **`cogtainer update <name> --lambdas`**: Only Python code in `src/cogos/` changed. Zips and uploads to existing Lambda.
- **`cogtainer update <name> --services`**: Need to restart ECS tasks (e.g. after ECR image push).
- **`cogtainer update <name> --services --image-tag <tag>`**: Deploy a specific Docker image to ECS.
- **Migrations**: DB migrations run automatically during image boot (`cogos start`). There is no separate migration command.

## Post-deploy

```bash
cogtainer status <cogtainer-name>
cogos status
```
