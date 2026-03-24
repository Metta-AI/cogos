# Simplify Dashboard Deployment

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Bake frontend into the Docker image, use a shared ECR repo with git-SHA tags, and make deploy = "update ECS image tag". Each cogent can pin to any SHA independently for canary rollouts and instant rollback.

**Architecture:** CI builds a single Docker image (frontend + backend) per commit, tagged by git SHA, pushed to a shared `cogent-dashboard` ECR repo. The deploy CLI updates the ECS task definition's image tag and forces a new deployment. No more S3 tarball download at runtime, no SIGUSR1 reload, no DOCKER_VERSION file.

**Tech Stack:** Docker, ECS Fargate, ECR, GitHub Actions, CDK (Python)

---

### Task 1: Bake frontend into the Docker image

**Files:**
- Modify: `dashboard/Dockerfile`
- Delete: `dashboard/entrypoint.sh`
- Create: `dashboard/start.sh` (simple process supervisor)

**Step 1: Rewrite Dockerfile to include frontend build**

Multi-stage build: stage 1 builds Next.js, stage 2 copies built output + Python backend.

```dockerfile
# Stage 1: Build Next.js frontend
FROM node:20-slim AS frontend
WORKDIR /build
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci
COPY dashboard/frontend/ ./
RUN npx next build

# Stage 2: Runtime
FROM python:3.12-slim
WORKDIR /app

# Install Node.js (to run standalone Next.js server)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python package
COPY pyproject.toml README.md /app/
COPY src/ /app/src/
COPY images/ /app/images/
RUN pip install --no-cache-dir .

# Copy built frontend from stage 1
COPY --from=frontend /build/.next/standalone /app/frontend/
COPY --from=frontend /build/.next/static /app/frontend/.next/static
COPY --from=frontend /build/public /app/frontend/public

# Simple start script
COPY dashboard/start.sh /app/start.sh
RUN chmod +x /app/start.sh

RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=5174
ENV HOSTNAME=0.0.0.0

EXPOSE 5174 8100
ENTRYPOINT ["/app/start.sh"]
```

**Step 2: Create simple start script**

`dashboard/start.sh` — no S3 download, no signal handling for reload, just start both processes:

```bash
#!/bin/sh
set -e

# Start FastAPI backend
python -m uvicorn cogos.api.app:app --host 0.0.0.0 --port 8100 &
BACKEND_PID=$!

# Start Next.js frontend
node /app/frontend/server.js &
FRONTEND_PID=$!

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' TERM INT

# Wait — if either exits, shut down
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
done

kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
exit 1
```

**Step 3: Delete old entrypoint and DOCKER_VERSION**

```bash
rm dashboard/entrypoint.sh dashboard/DOCKER_VERSION
```

**Step 4: Build and test locally**

```bash
docker build -f dashboard/Dockerfile -t dashboard:test --platform linux/amd64 .
docker run --rm -p 5174:5174 -p 8100:8100 dashboard:test
# Verify http://localhost:5174 loads and /healthz returns 200
```

**Step 5: Commit**

```bash
git add dashboard/Dockerfile dashboard/start.sh
git rm dashboard/entrypoint.sh dashboard/DOCKER_VERSION
git commit -m "feat: bake frontend into dashboard Docker image, remove S3 tarball download"
```

---

### Task 2: Create shared ECR repo via CDK

**Files:**
- Modify: `src/cogtainer/cdk/stacks/cogtainer_stack.py`
- Modify: `src/cogtainer/cdk/stacks/cogent_stack.py`

**Step 1: Add shared dashboard ECR repo to cogtainer stack**

In `cogtainer_stack.py`, add a shared ECR repo that all cogents pull from:

```python
# In CogtainerStack.__init__ or equivalent setup method:
self.dashboard_ecr = ecr.Repository(
    self, "DashboardEcr",
    repository_name="cogent-dashboard",
    removal_policy=RemovalPolicy.RETAIN,
    lifecycle_rules=[
        ecr.LifecycleRule(
            description="Keep last 50 images",
            max_image_count=50,
        ),
    ],
)
```

Export the repo URI as a CloudFormation output so cogent stacks can reference it.

**Step 2: Update cogent stack to use shared ECR repo**

In `cogent_stack.py` `_create_dashboard`, change image resolution:

```python
# Replace the current image resolution block (lines ~555-561) with:
dashboard_sha = self.node.try_get_context("dashboard_sha") or "latest"
dash_image = ecs.ContainerImage.from_registry(
    f"{self.account}.dkr.ecr.{self.region}.amazonaws.com/cogent-dashboard:{dashboard_sha}"
)
```

**Step 3: Remove DASHBOARD_ASSETS_S3 and DOCKER_VERSION from env**

In the `db_env` dict, remove:
- `"DASHBOARD_ASSETS_S3"` line
- `"DASHBOARD_DOCKER_VERSION"` line

Also remove the `docker_version` variable that reads from `dashboard/DOCKER_VERSION`.

**Step 4: Remove S3 dashboard/* permissions from task role**

In the task role S3 policy, remove `f"arn:aws:s3:::{bucket_name}/dashboard/*"` from the GetObject/PutObject resources, and remove `"dashboard/*"` from the ListBucket prefix condition. The dashboard no longer needs to read from S3 at runtime for frontend assets.

**Step 5: Commit**

```bash
git add src/cogtainer/cdk/stacks/cogtainer_stack.py src/cogtainer/cdk/stacks/cogent_stack.py
git commit -m "feat: shared cogent-dashboard ECR repo, remove S3 tarball env vars"
```

---

### Task 3: Update CI to build and push to shared ECR

**Files:**
- Modify: `.github/workflows/docker-build-dashboard.yml`

**Step 1: Simplify CI workflow**

Replace the current workflow. Key changes:
- Push to `cogent-dashboard` repo (shared) instead of per-cogtainer repo
- Tag with full SHA and short SHA (no more `dashboard-` prefix)
- Remove frontend tarball build + S3 upload (frontend is in the image now)
- Keep `update-versions` job but simplify to just `dashboard` (drop `dashboard_frontend`)

```yaml
name: Build Dashboard Image

on:
  push:
    branches: [main]
    paths:
      - "dashboard/**"
      - "src/dashboard/**"
      - "pyproject.toml"
      - ".github/workflows/docker-build-dashboard.yml"
  workflow_dispatch:

permissions:
  id-token: write
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      short_sha: ${{ steps.vars.outputs.short_sha }}
    steps:
      - uses: actions/checkout@v5

      - name: Get SHAs
        id: vars
        run: |
          echo "short_sha=$(git rev-parse --short ${{ github.sha }})" >> "$GITHUB_OUTPUT"

      - name: Build and push dashboard image
        uses: ./.github/actions/ecr-build
        with:
          image_name: cogent-dashboard
          dockerfile: dashboard/Dockerfile
          context: .
          aws_role: ${{ vars.AWS_ROLE }}
          aws_region: us-east-1
          # Tags: {sha-short}, {sha-full}, latest
          extra_tags: |
            ${{ github.sha }}
            ${{ steps.vars.outputs.short_sha }}
            latest

      - name: Summary
        run: |
          echo "### Dashboard Built" >> "$GITHUB_STEP_SUMMARY"
          echo "**Image:** \`cogent-dashboard:${{ steps.vars.outputs.short_sha }}\`" >> "$GITHUB_STEP_SUMMARY"
          echo "**Deploy:** \`cogent <name> update dashboard --sha ${{ steps.vars.outputs.short_sha }}\`" >> "$GITHUB_STEP_SUMMARY"

  update-versions:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Generate CI app token
        id: app-token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ secrets.APP_ID }}
          private-key: ${{ secrets.APP_PRIVATE_KEY }}

      - uses: actions/checkout@v5
        with:
          ref: main
          token: ${{ steps.app-token.outputs.token }}

      - name: Update versions defaults
        uses: ./.github/actions/update-versions
        with:
          component: dashboard
          version: ${{ needs.build.outputs.short_sha }}
          token: ${{ steps.app-token.outputs.token }}
```

**Step 2: Commit**

```bash
git add .github/workflows/docker-build-dashboard.yml
git commit -m "ci: push dashboard to shared ECR repo, remove S3 tarball upload"
```

---

### Task 4: Simplify the deploy CLI

**Files:**
- Modify: `src/cogtainer/update_cli.py`

**Step 1: Rewrite `update_dashboard` command**

Replace the entire `update_dashboard` function and remove `_build_and_upload_frontend`, the SIGUSR1/reload logic, and the `_docker_build_push_deploy` function. The new command:

```python
@update.command("dashboard")
@click.option("--sha", default=None, help="Git SHA to deploy (default: latest from versions.defaults.json)")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_dashboard(ctx: click.Context, sha: str | None, skip_health: bool):
    """Deploy a dashboard version by updating the ECS image tag.

    \b
    Resolves the SHA, updates the ECS task definition to point to
    cogent-dashboard:{sha} in shared ECR, and forces a new deployment.
    ~60-90s for the new task to be healthy.
    """
    t0 = time.monotonic()
    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    session = _get_admin_session()

    # Resolve SHA: explicit > versions.defaults.json > "latest"
    if not sha:
        sha = _read_default_version("dashboard") or "latest"
    click.echo(f"Deploying dashboard {sha} for cogent-{name}...")

    # Update ECS task def image tag and force new deployment
    ecr_repo = f"{ACCOUNT_ID}.dkr.ecr.{DEFAULT_REGION}.amazonaws.com/cogent-dashboard"
    image_uri = f"{ecr_repo}:{sha}"

    ecs_client = session.client("ecs", region_name=DEFAULT_REGION)
    service_arn = _find_dashboard_service(ecs_client, safe_name)
    _update_ecs_image(ecs_client, service_arn, image_uri)

    # Purge CDN cache
    click.echo("  Purging CDN cache...")
    try:
        from cogtainer.cloudflare import purge_cache
        from cogtainer.secret_store import SecretStore
        store = SecretStore(session=session)
        purge_cache(store)
    except Exception as e:
        click.echo(f"  Cache purge failed (non-fatal): {e}")

    if not skip_health:
        _wait_for_service_stable(ecs_client, safe_name)

    click.echo(f"  Dashboard: {click.style('deployed', fg='green')} ({time.monotonic() - t0:.1f}s)")
```

**Step 2: Add `_update_ecs_image` helper**

```python
def _update_ecs_image(ecs_client, service_arn: str, image_uri: str):
    """Update the ECS service's task def to use a new image and force deploy."""
    cluster = naming.cluster_name()
    services = ecs_client.describe_services(cluster=cluster, services=[service_arn])["services"]
    if not services:
        raise click.ClickException(f"Service not found: {service_arn}")

    task_def = ecs_client.describe_task_definition(
        taskDefinition=services[0]["taskDefinition"]
    )["taskDefinition"]

    # Update image in container definitions
    for c in task_def["containerDefinitions"]:
        if c.get("name") == "web":
            c["image"] = image_uri
            # Remove stale env vars
            c["environment"] = [
                e for e in c.get("environment", [])
                if e["name"] not in ("DASHBOARD_ASSETS_S3", "DASHBOARD_DOCKER_VERSION")
            ]

    # Register new task def revision
    reg_fields = [
        "family", "containerDefinitions", "taskRoleArn", "executionRoleArn",
        "networkMode", "requiresCompatibilities", "cpu", "memory",
    ]
    reg_kwargs = {k: task_def[k] for k in reg_fields if k in task_def}
    new_td = ecs_client.register_task_definition(**reg_kwargs)
    new_td_arn = new_td["taskDefinition"]["taskDefinitionArn"]
    click.echo(f"  Task def: {new_td_arn.split('/')[-1]}")

    # Force new deployment
    ecs_client.update_service(
        cluster=cluster,
        service=service_arn,
        taskDefinition=new_td_arn,
        forceNewDeployment=True,
    )
    click.echo(f"  Image: {image_uri}")
```

**Step 3: Remove dead code**

Delete these functions that are no longer needed:
- `_build_and_upload_frontend`
- `_docker_build_push_deploy`
- `_build_dashboard_tarball`
- `_read_docker_version`
- `_get_deployed_docker_version`
- Any reload-frontend related code

**Step 4: Remove `dashboard_frontend` from versions.defaults.json**

```json
{
  "executor": "d490d59",
  "dashboard": "9d6e713",
  "discord_bridge": "local",
  "lambda": "d490d59ed8a073d55e0f873beced59c470650f67",
  "cogos": "d490d59ed8a073d55e0f873beced59c470650f67"
}
```

**Step 5: Remove `--docker` flag from old `cogtainer deploy-dashboard` command**

Either delete `deploy-dashboard` entirely (if `cogent update dashboard` fully replaces it) or simplify to just call the new path.

**Step 6: Commit**

```bash
git add src/cogtainer/update_cli.py images/cogos/versions.defaults.json
git commit -m "feat: simplify dashboard deploy to ECS image tag swap, remove S3/reload paths"
```

---

### Task 5: Remove reload-frontend API endpoint

**Files:**
- Modify: `src/dashboard/api/admin.py` (or wherever `/admin/reload-frontend` lives)

**Step 1: Find and remove the endpoint**

Search for `reload-frontend` or `reload_frontend` in `src/dashboard/` and remove the endpoint + any signal-sending code.

**Step 2: Commit**

```bash
git commit -m "chore: remove unused reload-frontend admin endpoint"
```

---

### Task 6: Deploy and validate

**Step 1: Deploy CDK changes to create shared ECR repo**

```bash
cogent deploy cogtainer  # or however CDK deploy is triggered
```

**Step 2: Build and push initial image manually**

```bash
# Build the new baked image
docker build -f dashboard/Dockerfile -t cogent-dashboard:test --platform linux/amd64 .

# Tag and push to shared ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker tag cogent-dashboard:test <account>.dkr.ecr.us-east-1.amazonaws.com/cogent-dashboard:$(git rev-parse --short HEAD)
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/cogent-dashboard:$(git rev-parse --short HEAD)
```

**Step 3: Deploy to agora-alpha**

```bash
cogent agora.alpha update dashboard --sha $(git rev-parse --short HEAD)
```

**Step 4: Verify**
- Dashboard loads at the expected URL
- `/healthz` returns 200
- Frontend pages render correctly
- Backend API works

**Step 5: Test rollback**

```bash
# Deploy previous known-good SHA
cogent agora.alpha update dashboard --sha 9d6e713
# Verify it rolls back correctly
```
