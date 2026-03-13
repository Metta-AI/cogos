# Dashboard

Operational UI for each cogent. Runs as a single Docker container serving both the FastAPI backend and static Next.js frontend.

## Architecture

- **Backend**: FastAPI (Python), serves `/api/cogents/{name}/*` and `/ws/cogents/{name}`
- **Frontend**: Next.js static export, served by FastAPI when `DASHBOARD_STATIC_DIR` is set
- **Database**: RDS Data API (same Aurora cluster as the cogtainer)
- **Hosting**: ECS Fargate in the polis account (`cogent-polis` cluster), behind ALB with HTTPS
- **Domain**: `{safe_name}.softmax-cogents.com` (managed by polis)

## Deployment

```bash
cogent dr.beta dashboard deploy    # Delegates to: polis dashboard deploy dr.beta
```

This runs `polis dashboard deploy` which:
1. Reads cogent identity from polis secrets (cert ARN, domain)
2. Reads cogtainer stack outputs (DB ARNs)
3. CDK deploys the dashboard stack (ALB, ECS service, task definition)
4. Updates Route53 DNS to point at the ALB

### First-time setup

```bash
polis cogents create dr.beta       # Register identity (domain, cert, secrets)
cogent dr.beta dashboard deploy    # Deploy the dashboard
```

## Docker Image

`Dockerfile` at project root, multi-stage build:

1. **Stage 1 (Node)**: `NEXT_EXPORT=1` builds Next.js as static HTML to `/app/out`
2. **Stage 2 (Python)**: Installs FastAPI/boto3/pydantic, copies `src/` + static files, runs uvicorn on port 8100

The container serves everything on one port:
- `/api/*`, `/ws/*` — FastAPI API and WebSocket
- `/healthz` — health check (used by ALB target group)
- `/*` — static frontend (SPA fallback to `index.html`)

## Local Development

```bash
cogent local dashboard serve --db local   # Backend (8100) + Next.js dev server (5200 by default)
cogent dr.beta dashboard serve --db prod  # Live DB via polis
```

In dev mode, Next.js proxies `/api/*` to the backend via `rewrites` in `next.config.ts`.

## Key Files

```
Dockerfile                              # Multi-stage build
dashboard/frontend/
  next.config.ts                        # NEXT_EXPORT=1 -> static export, else standalone + rewrites
  src/lib/api.ts                        # All API calls (relative paths)
src/dashboard/
  app.py                                # FastAPI app + static file serving
  config.py                             # Settings (env prefix: DASHBOARD_)
  db.py                                 # Repository singleton (Data API or local)
  routers/                              # API route handlers
src/cli/dashboard.py                    # CLI: serve, deploy, login, keys
src/polis/cli.py                        # polis dashboard deploy/destroy
```

## Environment Variables (container)

| Variable | Description |
|----------|-------------|
| `DASHBOARD_STATIC_DIR` | Path to static frontend files (enables serving) |
| `DASHBOARD_COGENT_NAME` | Cogent name |
| `DB_CLUSTER_ARN` | Aurora cluster ARN (Data API) |
| `DB_SECRET_ARN` | Secrets Manager ARN for DB auth |
| `DB_NAME` | Database name (`cogent`) |
| `USE_LOCAL_DB` | Set to `1` to use LocalRepository (JSON file at `~/.cogent/local/cogos_data.json`) instead of RDS Data API. For local dev only. |

## Database Connection

The dashboard **requires** RDS Data API credentials (`DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`). If these are missing, the app will fail to start rather than silently returning empty data.

For local development without AWS access, set `USE_LOCAL_DB=1` to use the LocalRepository which persists to `~/.cogent/local/cogos_data.json`. Populate it with `cogent local cogos image boot cogent-v1 --clean`.
