# Dashboard

Operational UI for each cogent. Runs as a single Docker container serving both the FastAPI backend and static Next.js frontend.

See root [AGENTS.md](../AGENTS.md) for local development commands, database connection details, and general architecture.

## Architecture

Docker multi-stage build (`Dockerfile` at project root):

1. **Stage 1 (Node)**: `NEXT_EXPORT=1` builds Next.js as static HTML to `/app/out`
2. **Stage 2 (Python)**: Installs FastAPI/boto3/pydantic, copies `src/` + static files, runs uvicorn on port 8100

In production, the container serves everything on a single port (8100):
- `/api/*`, `/ws/*` — FastAPI API and WebSocket
- `/healthz` — health check (used by ALB target group)
- `/*` — static frontend (SPA fallback to `index.html`)

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
| `USE_LOCAL_DB` | Set to `1` to use LocalRepository instead of RDS Data API. The data directory is resolved from the cogtainer config. For local dev only. |
