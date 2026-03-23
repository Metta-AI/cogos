# Dashboard

Operational UI for each cogent. Runs as a single Docker container serving both the FastAPI backend and static Next.js frontend.

## Architecture

- **Backend**: FastAPI (Python), serves `/api/cogents/{name}/*` and `/ws/cogents/{name}`
- **Frontend**: Next.js static export, served by FastAPI when `DASHBOARD_STATIC_DIR` is set
- **Database**: RDS Data API (same Aurora cluster as the cogtainer)
- **Hosting**: ECS Fargate in the cogtainer (`cogtainer` cluster), behind ALB with HTTPS
- **Domain**: `{safe_name}.<your-domain>` (managed by cogtainer)

## Deployment

```bash
cogtainer update <name> --services --image-tag dashboard-latest
```

CI builds the dashboard Docker image automatically. Deploy via the `cogtainer` CLI once the image is available.

### First-time setup

```bash
cogent create <name>                    # Register identity (domain, cert, secrets)
cogtainer update <name> --services      # Deploy the dashboard
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
cogos dashboard start       # Backend + Next.js dev server in background
cogos dashboard stop        # Stop both servers
cogos dashboard reload      # Restart (stop + start)
```

**IMPORTANT: Always use `cogos dashboard start/stop/reload`.** Never start `uvicorn` or `next dev` manually — the dashboard requires env vars (`DASHBOARD_BE_PORT`, `COGOS_LOCAL_DATA`, `USE_LOCAL_DB`) derived from `~/.cogos/cogtainers.yml` that differ per cogtainer. Manual starts will connect to the wrong port or database.

In dev mode, Next.js proxies `/api/*` to the backend via `rewrites` in `next.config.ts`, using `DASHBOARD_BE_PORT` to determine the backend port.

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
src/cli/cogtainer.py                    # cogtainer dashboard deploy/destroy
```

## Environment Variables (container)

| Variable | Description |
|----------|-------------|
| `DASHBOARD_STATIC_DIR` | Path to static frontend files (enables serving) |
| `DASHBOARD_COGENT_NAME` | Cogent name |
| `DB_CLUSTER_ARN` | Aurora cluster ARN (Data API) |
| `DB_SECRET_ARN` | Secrets Manager ARN for DB auth |
| `DB_NAME` | Database name (`cogent`) |
| `USE_LOCAL_DB` | Set to `1` to use LocalRepository instead of RDS Data API. Default path is `~/.cogos/local/cogos_data.json`; source `dashboard/ports.sh` to use `.local/cogos/` under the checkout, or set `COGOS_LOCAL_DATA` to override. For local dev only. |

## Database Connection

The dashboard **requires** RDS Data API credentials (`DB_CLUSTER_ARN`, `DB_SECRET_ARN`, `DB_NAME`). If these are missing, the app will fail to start rather than silently returning empty data.

For local development without AWS access, set `USE_LOCAL_DB=1` to use the LocalRepository. Source `dashboard/ports.sh` to use `.local/cogos/` under the checkout, or set `COGOS_LOCAL_DATA` to override the path. Populate it with `COGENT=local cogos image boot cogos --clean`.
