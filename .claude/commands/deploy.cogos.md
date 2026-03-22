Deploy CogOS changes (image data, DB schema, executor logic) with minimal disruption.

Human-readable reference: [docs/deploy.md](../../docs/deploy.md)

## Pre-flight

1. Ensure no uncommitted changes: `git status --porcelain` must be empty. If dirty, stop and ask.
2. Pull latest: `git pull --ff-only`. If it fails (diverged), stop and ask.
3. Identify the cogent name from context (default: `dr.alpha`).

## Decide what to deploy

Run `git diff HEAD~1 --name-only` (or broader if needed) and categorize:

| Changed paths | What's needed |
|---|---|
| `images/**` only (files, init scripts) | **Image reboot** — just update DB state. No infra change. |
| `src/cogos/db/migrations/**` | **RDS migration** — schema change needed first. |
| `src/cogos/executor/**` or `src/cogos/sandbox/**` | **Lambda update** — executor code changed, redeploy Lambda. |
| `src/cogos/capabilities/**` | **Lambda update + image reboot** — capability code in Lambda, definitions in image. |
| `src/cogos/files/**` or `src/cogos/image/**` | **Lambda update** — these run inside Lambda. |
| `src/dashboard/**` or `dashboard/frontend/**` | **Wrong skill!** Use `/deploy.dashboard` instead. |
| No cogos changes | Nothing to deploy. Tell the user. |

## Commands reference

```bash
# Boot image and start dispatcher (upsert capabilities, files, processes into DB)
cogent <name> cogos start

# Boot with clean slate (wipe all tables first)
cogent <name> cogos start --clean

# Start without re-booting image
cogent <name> cogos start --skip-boot

# Stop the dispatcher
cogent <name> cogos stop

# Restart (stop + boot + start)
cogent <name> cogos restart

# Run DB migrations only
cogent <name> cogtainer update rds

# Update Lambda function code only
cogent <name> cogtainer update lambda

# Update all components (Lambda + RDS + dashboard + discord bridge)
cogent <name> cogtainer update
```

## Typical sequences

**Image-only change** (edited files in `images/`, e.g. prompt text, new capability definition):
```bash
cogent <name> cogos restart
```

**Executor code change** (edited `src/cogos/executor/`, `src/cogos/sandbox/`, etc.):
```bash
cogent <name> cogtainer update lambda
cogent <name> cogos restart  # if image also changed
```

**Schema migration + executor change**:
```bash
cogent <name> cogtainer update rds
cogent <name> cogtainer update lambda
cogent <name> cogos restart
```

## Post-deploy

Verify by running a quick process test:
```bash
cogent <name> cogos process list
cogent <name> cogos status
```
