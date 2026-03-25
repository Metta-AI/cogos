Deploy CogOS changes (image data, DB schema, executor logic) with minimal disruption.

Human-readable reference: [docs/deploy.md](../../docs/deploy.md)

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Ensure the right cogent is selected: check `.env` for COGTAINER/COGENT, or run `cogent select <name>` to set them. Verify with `cogos status`.

## Check: is this the right skill?

Run `git diff HEAD~1 --name-only` (or broader if needed) and check:

| Changed paths | Action |
|---|---|
| `images/**`, `src/cogos/**`, `src/cogos/db/migrations/**` | **This skill** — read on |
| `src/dashboard/**` or `dashboard/frontend/**` | **Wrong skill** — use `/deploy.dashboard` |
| `src/cogtainer/cdk/**`, IAM, VPC, ALB changes | **Wrong skill** — use `/deploy.cogtainer` |
| No cogos changes | Nothing to deploy. Tell the user. |

See [docs/deploy.md](../../docs/deploy.md) for the full decision tree.

## Commands reference

```bash
# Boot image and start dispatcher (upsert capabilities, files, processes into DB; runs migrations)
cogos start

# Boot with clean slate (wipe all tables first)
cogos start --clean

# Start without re-booting image
cogos start --skip-boot

# Stop the dispatcher
cogos stop

# Restart (stop + boot + start)
cogos restart

# Per-cogent deploys (recommended)
cogent update lambda                  # Update Lambda function code
cogent update rds                     # Run DB schema migrations
cogent update all                     # Update all components

# Bulk cogtainer deploys (secondary)
cogtainer update <cogtainer-name> --lambdas
cogtainer update <cogtainer-name> --services
cogtainer update <cogtainer-name>
```

## Typical sequences

**Image-only change** (edited files in `images/`, e.g. prompt text, new capability definition):
```bash
cogos restart
```

**Executor code change** (edited `src/cogos/executor/`, `src/cogos/sandbox/`, etc.):
```bash
cogent update lambda
cogos restart  # if image also changed
```

**Schema migration + executor change** (migrations run during image boot):
```bash
cogent update lambda
cogos restart
```

## Post-deploy

Verify by running a quick process test:
```bash
cogos process list
cogos status
```
