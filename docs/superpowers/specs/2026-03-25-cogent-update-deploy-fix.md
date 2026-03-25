# Spec: Wire `cogent update` subcommands and fix deploy CLI/docs

## Context

PR #237 was supposed to contain 10 file changes but only the test fix (`tests/cogtainer/test_update_cli.py`) actually merged. The code and doc changes were lost during a `gt sync -f` that reset local main. This spec describes exactly what needs to be re-done.

## What needs to happen

### 1. Wire `update_cli.py` into the `cogent` CLI (`src/cogtainer/cogent_cli.py`)

The update subcommands (`update lambda`, `update dashboard`, `update rds`, `update all`, `update stack`, etc.) live in `src/cogtainer/update_cli.py` but are only mounted on an unreachable `cogtainer` group in `src/cogtainer/cli.py`. Wire them into the `cogent` CLI entry point.

Changes to `cogent_cli.py`:
- Add `import os`
- Make `cli()` group accept `@click.pass_context`, call `ctx.ensure_object(dict)`
- In the group callback, resolve cogtainer/cogent from config, populate `ctx.obj["cogtainer_name"]` and `ctx.obj["cogent_name"]`
- For AWS cogtainers, call `runtime._get_db_info()` and set `DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME` env vars (the runtime assumes the cogtainer role, which is needed for DB access)
- Inject `cogtainer_name` into `cogtainer.deploy_config._config_cache` so `naming.cluster_name()` resolves correctly
- At the bottom: `from cogtainer.update_cli import update; cli.add_command(update)`

### 2. Fix version resolution in `update_cli.py`

Currently `_read_boot_versions()` reads from the DB boot manifest, which is stale between reboots. Change it to read from local `images/cogos/versions.defaults.json` first (updated by CI on every push to main), falling back to DB.

- Add `_read_local_versions()` that reads and returns `images/cogos/versions.defaults.json`
- Modify `_read_boot_versions()` to call `_read_local_versions()` first, fall back to DB

### 3. Improve ECR image warning in `update_cli.py`

`_check_ecr_image_for_commit()` currently shows a generic warning when HEAD doesn't match CI. Add a `deploy_sha` parameter so it can say "Deploying version X from boot manifest" instead.

- Add `deploy_sha: str | None = None` param to `_check_ecr_image_for_commit`
- In `update_lambda`, move version resolution BEFORE the ECR check, pass resolved sha
- Update warning message to include the deploying version

### 4. Replace `RdsDataApiRepository.create()` with `create_repository()` factory

Three places in `update_cli.py` hardcode `RdsDataApiRepository.create()`. Replace with `from cogos.db.factory import create_repository`.

Also in `update_rds`: `apply_schema()` needs an rds-data client — use `_get_admin_session()` to get a cogtainer-account session, create the client from that.

### 5. Add boot manifest write-back (best-effort)

Add `_update_boot_versions(name, {"lambda": sha, ...})` that writes deployed versions back to `mnt/boot/versions.json` in the DB via FileStore. Silently catch failures (DB env resolution is broken from the `cogent` CLI path — known issue).

Call it after successful lambda and dashboard deploys.

### 6. Add `_ensure_db_env` call in `update_lambda`

Add `_ensure_db_env(name)` early in `update_lambda` so DB env vars are available for the content deploy timestamp and boot manifest write-back.

### 7. Update all deploy docs (7 files)

All docs should point to `cogent update <subcommand>` as primary deploy path:

**`docs/deploy.md`:**
- Architecture table: `cogent update lambda`, `cogent update dashboard`, separate rows for per-cogent vs shared CDK
- Decision tree: use `cogent update` commands
- Command reference: per-cogent section (recommended) + bulk cogtainer section (secondary, needs explicit flags)
- Typical sequences: use `cogent update` commands
- No `--from-source` in recommended commands

**`AGENTS.md` (deploy section around line 215):**
- Per-cogent deploys as primary, bulk cogtainer as secondary
- Dashboard ECR tags are `sha-{sha}` in `cogent-dashboard` repo, not `dashboard-{sha}`
- Warning about `--image-tag` blast radius

**`docs/agents.md`:**
- Fix "common version mismatches" to use `cogent update dashboard` / `cogent update lambda`
- Fix "full deploy + test cycle" to use `cogent update lambda`

**`docs/cogtainer/cli.md`:**
- Add `cogent update <subcommand>` section as primary
- Keep `cogtainer update <name>` as secondary with options table
- No `--from-source` in options

**`.claude/commands/deploy.cogos.md`:**
- Commands reference: `cogent update lambda`, `cogent update rds`, `cogent update all`
- Typical sequences: `cogent update lambda` instead of `cogtainer update --lambdas`

**`.claude/commands/deploy.dashboard.md`:**
- Replace nonexistent `cogtainer deploy-dashboard` with `cogent update dashboard`

**`.claude/commands/deploy.cogtainer.md`:**
- Commands reference: `cogent update` subcommands as primary
- Distinguish per-cogent CDK (`cogent update stack`) from shared infra (`cogtainer update <name>`)

### 8. Update test (`tests/cogtainer/test_update_cli.py`)

Already merged in PR #237. The test now mocks `_get_admin_session`, `cogos.db.factory.create_repository`, and `apply_schema(client=...)`. Verify it still passes after the code changes.

## Verification

```bash
uv run cogent update --help          # should show lambda, dashboard, rds, all, stack, etc.
uv run cogent update lambda --help   # should work
uv run ruff check src/cogtainer/cogent_cli.py src/cogtainer/update_cli.py
uv run python -m pytest tests/cogtainer/ -x -q
```

## Known issues to NOT fix in this PR

- Boot manifest write-back silently fails (DB env resolution from cogent CLI uses wrong account)
- Multi-statement SQL migration in `apply_cogos_sql_migrations` fails on RDS Data API
- CDN cache purge fails with "COGTAINER env var not set"
