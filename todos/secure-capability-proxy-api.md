# Secure Capability Proxy API — Implementation Plan

## Problem

CogOS sandboxes currently access capabilities directly because they run in the
same AWS account with full DB/Lambda access. Remote executors (running on other
machines) have no way to call capabilities — they'd need direct RDS Data API
credentials and AWS IAM roles.

We need:
1. A **CogOS API service** that proxies capability calls over HTTP with auth
2. **Dashboard separated from API** — the API is its own service; the dashboard
   consumes it

## Architecture

```
┌──────────────┐    HTTPS + JWT     ┌──────────────┐
│   Remote     │ ─────────────────► │  CogOS API   │
│   Executor   │                    │  (FastAPI)    │
└──────────────┘                    │              │
                                    │  /api/v1/    │
┌──────────────┐    HTTPS + JWT     │  capabilities│
│   Dashboard  │ ─────────────────► │  /invoke     │
│   (Next.js)  │                    └──────┬───────┘
└──────────────┘                           │
                                    ┌──────▼───────┐
                                    │  Repository  │
                                    │  (RDS)       │
                                    └──────────────┘
```

## Steps

### Step 1: Create `src/cogos_api/` package — the standalone API service

New files:
- `src/cogos_api/__init__.py`
- `src/cogos_api/app.py` — FastAPI app factory with lifespan, CORS, health check
- `src/cogos_api/config.py` — Settings (host, port, cors, jwt secret ref)
- `src/cogos_api/db.py` — Singleton repository (same pattern as `dashboard/db.py`)
- `src/cogos_api/auth.py` — JWT token verification middleware

The API service owns the `/api/v1/` namespace. It connects to the same RDS
database as the dashboard but runs as a separate process/container.

### Step 2: JWT-based auth for executor sessions

Auth flow:
1. Executor starts → requests a session token via a bootstrap endpoint
   (`POST /api/v1/sessions`) using a pre-shared executor key from Secrets Manager
2. API returns a short-lived JWT containing `process_id`, `cogent`, `exp`
3. All subsequent capability calls include `Authorization: Bearer <jwt>`
4. API validates JWT signature + expiry on every request

Token module (`src/cogos_api/auth.py`):
- `create_session_token(process_id, cogent, ttl=3600)` → JWT string
- `verify_token(token)` → claims dict or raise 401
- Signing key: read from `cogtainer/shared/jwt-signing-key` in Secrets Manager
  (or `COGOS_API_JWT_SECRET` env var for local dev)

Dependencies: `PyJWT` (already in pyproject.toml).

### Step 3: Capability invoke endpoint

`POST /api/v1/capabilities/{cap_name}/{method_name}`

Request body:
```json
{
  "args": {},           // keyword arguments for the method
  "scope": {}           // optional scope overrides (intersected with grant)
}
```

Response:
```json
{
  "result": { ... },    // serialized return value (Pydantic .model_dump() or repr)
  "error": null         // or error string
}
```

Implementation (`src/cogos_api/routers/capabilities.py`):
1. Extract `process_id` from JWT claims
2. Load process capabilities from DB (same logic as `sandbox/server.py:_build_capability_proxies`)
3. Find the matching capability by grant name
4. Instantiate the capability class with repo + process_id
5. Apply scope from grant config + request scope (intersection)
6. Call the method with provided args
7. Serialize result (Pydantic models → dict, other → repr)

Reuse `_build_capability_proxies` logic by extracting it into a shared module
(`src/cogos/capabilities/loader.py`).

### Step 4: Session management endpoint

`POST /api/v1/sessions` — Create executor session
- Auth: `X-Executor-Key` header (pre-shared key from Secrets Manager)
- Body: `{ "process_id": "<uuid>", "cogent": "<name>" }`
- Returns: `{ "token": "<jwt>", "expires_at": "..." }`
- Validates that the process exists and has a RUNNING run

`GET /api/v1/sessions/me` — Introspect current session
- Auth: Bearer JWT
- Returns: process info, granted capabilities, remaining TTL

### Step 5: Capability discovery endpoints

`GET /api/v1/capabilities` — List capabilities available to the session's process
`GET /api/v1/capabilities/{cap_name}` — Capability detail + methods
`GET /api/v1/capabilities/{cap_name}/methods` — Method signatures

These mirror the existing dashboard router but are scoped to the
authenticated process's grants.

### Step 6: Extract shared capability loader

Move the proxy-building logic from `sandbox/server.py:_build_capability_proxies`
into `src/cogos/capabilities/loader.py` so both the sandbox server and the
API service use the same code path for:
- Resolving handler dotted paths
- Instantiating capability classes
- Applying scope config

### Step 7: HTTP capability client for remote executors

`src/cogos/capabilities/http_client.py` — A thin client class that implements
the same interface as local capability proxies but sends HTTP requests to the
CogOS API:

```python
class HttpCapabilityProxy:
    """Proxies capability method calls to the CogOS API over HTTP."""
    def __init__(self, api_url: str, token: str, cap_name: str): ...
    def __getattr__(self, method_name: str) -> Callable: ...
```

This allows remote executors to use capabilities with the same Python API
as local sandboxes — `data.query(...)` transparently becomes an HTTP POST.

### Step 8: Refactor dashboard to consume the API

Update `src/dashboard/app.py`:
- Remove DB-heavy routes that duplicate API functionality
- Dashboard routers call the CogOS API service instead of accessing the
  repository directly (where applicable)
- Keep dashboard-specific routes (static files, SPA fallback, frontend reload)
- Dashboard authenticates to the API with a service-level JWT or API key

This is a gradual migration — start by having the API service run alongside
the dashboard, then move dashboard routes to call the API.

### Step 9: Tests

- `tests/cogos_api/test_auth.py` — JWT creation/verification, expiry, invalid tokens
- `tests/cogos_api/test_capabilities.py` — Invoke endpoint with mocked capabilities
- `tests/cogos_api/test_sessions.py` — Session creation, introspection
- `tests/cogos/capabilities/test_loader.py` — Extracted loader logic
- `tests/cogos/capabilities/test_http_client.py` — HTTP proxy client

## File Summary

New files:
```
src/cogos_api/__init__.py
src/cogos_api/app.py
src/cogos_api/config.py
src/cogos_api/db.py
src/cogos_api/auth.py
src/cogos_api/routers/__init__.py
src/cogos_api/routers/capabilities.py
src/cogos_api/routers/sessions.py
src/cogos/capabilities/loader.py
src/cogos/capabilities/http_client.py
tests/cogos_api/test_auth.py
tests/cogos_api/test_capabilities.py
tests/cogos_api/test_sessions.py
```

Modified files:
```
src/cogos/sandbox/server.py          — import from loader.py instead of inline
src/dashboard/app.py                 — note: gradual migration, minimal changes in step 1
pyproject.toml                       — add cogos-api script entry point
```
