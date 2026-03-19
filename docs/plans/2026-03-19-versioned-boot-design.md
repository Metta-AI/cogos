# Versioned Boot Design

## Problem

Components (executor, dashboard, lambdas) are deployed independently with no
explicit binding between them. There is no way to know what combination a
running cogent uses, no pre-flight verification that artifacts exist, and no
support for running different cogents on different versions.

## Goals

- **Multi-tenant divergence** — cogent-alpha runs version X while cogent-beta
  runs version Y.
- **Reproducibility** — know exactly what is running and recreate it.
- **Deployment confidence** — verify all artifacts exist before booting.

## Design

### Version Manifest

`/mnt/boot/versions.json` is the single source of truth for what a cogent is
running:

```json
{
  "epoch": 5,
  "cogent_name": "dr.alpha",
  "booted_at": "2026-03-19T14:30:00Z",
  "components": {
    "executor": "abc1234",
    "dashboard": "def5678",
    "dashboard_frontend": "ghi9012",
    "discord_bridge": "pqr2345",
    "lambda": "jkl3456",
    "cogos": "mno7890"
  }
}
```

- **epoch** — monotonic counter from the DB, incremented on each boot.
- **components** — each value is a git short SHA. Resolves to artifacts by
  convention:
  - `executor` → ECR tag `executor-{sha}`
  - `dashboard` → ECR tag `dashboard-{sha}`
  - `dashboard_frontend` → `s3://{artifacts_bucket}/dashboard/{sha}/frontend.tar.gz`
  - `discord_bridge` → ECR tag `discord-bridge-{sha}`
  - `lambda` → `s3://{artifacts_bucket}/lambda/{sha}/lambda.zip`
  - `cogos` → git ref for the image spec code

### Defaults File

`images/cogent-v1/versions.defaults.json` is checked into git and tracks the
latest known-good version for each component:

```json
{
  "executor": "abc1234",
  "dashboard": "def5678",
  "dashboard_frontend": "ghi9012",
  "discord_bridge": "pqr2345",
  "lambda": "jkl3456",
  "cogos": "mno7890"
}
```

CI auto-updates this file on main after building artifacts. Each workflow owns
its component key:

- `docker-build-executor.yml` → `executor`
- `docker-build-dashboard.yml` → `dashboard`, `dashboard_frontend`
- `docker-build-discord.yml` → `discord_bridge`
- Lambda build workflow → `lambda`
- Any workflow → `cogos` (merge commit SHA)

### Boot Flow

`cogos image boot` does the following in order:

1. **Resolve versions** — Load `versions.defaults.json`, apply CLI overrides
   (`--executor abc123`).
2. **Verify artifacts exist** — For each component:
   - ECR: `describe-images --image-ids imageTag=executor-{sha}`
   - S3: `head-object --key lambda/{sha}/lambda.zip`
   - Hard fail if any artifact is missing.
3. **Read epoch from DB** — Increment by 1.
4. **Write `/mnt/boot/versions.json`** — Full manifest.
5. **Continue existing boot sequence** — Migrate DB, upsert capabilities,
   upsert processes, etc.

**Dry-run:** `cogos image boot --dry-run` runs steps 1-2 only, prints the
resolved version map and verification results, exits.

**Local dev:** Verification is skipped (no ECR/S3). Versions default to
`"local"` unless overridden. File lands at `.local/cogos/mnt/boot/versions.json`.

### Runtime Component Resolution

Components read `versions.json` to resolve which artifact version to use:

- **Orchestrator lambda** — Reads `executor` version, passes as ECS task image
  override (`executor-{sha}`) when dispatching.
- **ECS task dispatch** — Overrides container image to
  `{ecr_repo}:executor-{sha}`.
- **Dashboard deploy** — Uses `dashboard-{sha}` for ECS image,
  `s3://{bucket}/dashboard/{sha}/frontend.tar.gz` for frontend.
- **Discord bridge deploy** — Uses `discord-bridge-{sha}` for ECS image.
- **Lambda update** — Deploys from `s3://{bucket}/lambda/{sha}/lambda.zip`.

`cogtainer update lambda` and `cogtainer update ecs` read from the boot
manifest rather than taking explicit `--tag` flags.

## Changes

### New files

- `images/cogent-v1/versions.defaults.json`

### Modified files

| File | Change |
|---|---|
| `src/cogos/image/boot.py` | Version resolution, artifact verification, write `versions.json` |
| `src/cogtainer/lambdas/orchestrator/handler.py` | Read executor version from manifest, pass as ECS image override |
| `src/cogtainer/cdk/constructs/compute.py` | Remove hardcoded image tags, support dynamic override |
| `src/cogtainer/cli.py` | `update lambda` and `update ecs` read from manifest |
| `.github/workflows/docker-build-executor.yml` | Auto-update `versions.defaults.json` on main |
| `.github/workflows/docker-build-dashboard.yml` | Same |
| `.github/workflows/docker-build-discord.yml` | Same |
| CI lambda build workflow | Same |
