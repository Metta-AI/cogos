# Unify API Tokens Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace JWT + executor-key auth with a single ExecutorToken system, add token CRUD API endpoints, and add a dashboard UI for creating tokens with a copy-paste Claude Code launch command.

**Architecture:** All API endpoints (dashboard routes + capability proxy) validate a single `Authorization: Bearer <token>` by SHA-256 hashing and looking up in the `executor_tokens` table. The capability proxy routes accept `X-Process-Id` header to identify the calling process. JWT machinery, sessions router, and executor-key config are removed entirely. Dashboard frontend gets a token management section in the Executors panel.

**Tech Stack:** Python/FastAPI backend, React/Next.js frontend, existing ExecutorToken model + repo methods.

---

### Task 1: Replace JWT auth with ExecutorToken validation in capability routes

The capability proxy (`/api/v1/capabilities/...`) currently uses JWT via `get_claims()` which returns `TokenClaims(process_id, cogent, ...)`. Replace this with ExecutorToken validation + `X-Process-Id` header.

**Files:**
- Modify: `src/cogos/api/auth.py`
- Modify: `src/cogos/api/routers/capabilities.py`
- Test: `tests/cogos/api/test_capabilities.py`
- Test: `tests/cogos/api/test_auth.py`

**Step 1: Create new auth dependency**

Replace the contents of `src/cogos/api/auth.py` with:

```python
"""Token-based authentication for the CogOS API.

All endpoints validate a Bearer token by SHA-256 hashing it and looking
up the hash in the executor_tokens table.  Capability proxy routes also
require an X-Process-Id header to identify the calling process.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request

from cogos.api.db import get_repo

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Validated auth context from a Bearer token."""
    token_name: str
    process_id: str  # from X-Process-Id header, empty if not provided


def validate_token(request: Request) -> AuthContext:
    """FastAPI dependency — validate Bearer token against stored ExecutorToken hashes.

    Also reads optional X-Process-Id header for capability proxy routes.
    """
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key", "")

    # Accept token from either Authorization: Bearer or x-api-key header
    token = ""
    if auth.startswith("Bearer "):
        token = auth[7:]
    elif api_key:
        token = api_key

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    repo = get_repo()
    executor_token = repo.get_executor_token_by_hash(token_hash)
    if executor_token is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    process_id = request.headers.get("x-process-id", "")

    return AuthContext(
        token_name=executor_token.name,
        process_id=process_id,
    )
```

**Step 2: Update capability routes to use new auth**

In `src/cogos/api/routers/capabilities.py`, replace:
- `from cogos.api.auth import TokenClaims, get_claims` → `from cogos.api.auth import AuthContext, validate_token`
- All `claims: TokenClaims = Depends(get_claims)` → `auth: AuthContext = Depends(validate_token)`
- `_get_proxies(claims)` → `_get_proxies(auth)` which uses `auth.process_id`
- Add 400 error if `process_id` is empty on routes that need it

**Step 3: Update HttpCapabilityClient to skip JWT session bootstrap**

In `src/cogos/capabilities/http_client.py`:
- Replace `from_executor_key()` with `from_token()` that just stores the token directly
- Add `X-Process-Id` header to all requests
- Remove session_info() method

**Step 4: Update tests**

Update `tests/cogos/api/test_auth.py` — remove JWT tests, add ExecutorToken validation tests.
Update `tests/cogos/api/test_capabilities.py` — use Bearer token + X-Process-Id instead of JWT.

**Step 5: Commit**

```bash
git commit -m "refactor: replace JWT auth with ExecutorToken validation"
```

---

### Task 2: Remove JWT machinery and sessions router

**Files:**
- Modify: `src/cogos/api/app.py` — remove sessions router import and include
- Delete: `src/cogos/api/routers/sessions.py`
- Modify: `src/cogos/api/config.py` — remove jwt_secret, jwt_ttl, executor_key fields
- Delete: `tests/cogos/api/test_sessions.py`
- Modify: `pyproject.toml` — remove PyJWT dependency

**Step 1: Remove sessions router from app.py**

In `src/cogos/api/app.py`, remove:
```python
from cogos.api.routers import sessions
app.include_router(sessions.router, prefix="/api/v1")
```

Also remove the comment `# ── Executor proxy routers (JWT-authenticated) ─────────────`.

**Step 2: Delete sessions.py**

```bash
rm src/cogos/api/routers/sessions.py
rm tests/cogos/api/test_sessions.py
```

**Step 3: Clean up config.py**

Remove from `ApiSettings`:
- `jwt_secret`
- `jwt_secret_id`
- `jwt_ttl_seconds`
- `executor_key`
- `executor_key_secret_id`

**Step 4: Remove PyJWT from pyproject.toml**

Remove `PyJWT>=2.8` from dependencies.

**Step 5: Verify no remaining JWT imports**

```bash
grep -rn "import jwt\|from jwt\|PyJWT\|create_session_token\|verify_token\|get_claims\|TokenClaims\|verify_executor_key\|_get_signing_key\|_get_executor_key" src/ tests/
```

Fix any remaining references.

**Step 6: Run tests**

```bash
pytest tests/cogos/api/ -v
```

**Step 7: Commit**

```bash
git commit -m "refactor: remove JWT sessions and executor-key auth"
```

---

### Task 3: Unify dashboard executor route auth with shared validate_token

The dashboard executor routes in `src/dashboard/routers/executors.py` have their own `_validate_executor_token()` function. Replace with the shared `validate_token` from `cogos.api.auth`.

**Files:**
- Modify: `src/dashboard/routers/executors.py`
- Test: `tests/dashboard/test_routers_executors.py`

**Step 1: Replace inline validation with shared dependency**

In `src/dashboard/routers/executors.py`:
- Remove `_validate_executor_token()` function
- Import `from cogos.api.auth import validate_token`
- Replace manual `authorization: str | None = Header(None)` + validation logic with `Depends(validate_token)` on protected routes
- Unprotected read routes (list, get) stay as-is

**Step 2: Update tests**

**Step 3: Commit**

```bash
git commit -m "refactor: use shared validate_token in executor routes"
```

---

### Task 4: Add token CRUD API endpoints

**Files:**
- Modify: `src/dashboard/routers/executors.py`
- Test: `tests/dashboard/test_routers_executors.py`

**Step 1: Add token management endpoints**

Add to `src/dashboard/routers/executors.py`:

```python
class CreateTokenRequest(BaseModel):
    name: str

class CreateTokenResponse(BaseModel):
    name: str
    token: str  # raw token, shown once only
    launch_command: str  # copy-paste command for claude

class TokenItem(BaseModel):
    name: str
    scope: str
    created_at: str | None = None
    revoked: bool = False

class TokensResponse(BaseModel):
    tokens: list[TokenItem]


@router.post("/executor-tokens", response_model=CreateTokenResponse)
def create_token(name: str, body: CreateTokenRequest, request: Request):
    """Create a new executor token. Returns the raw token once."""
    import hashlib, secrets
    from cogos.db.models import ExecutorToken

    repo = get_repo()
    raw_token = secrets.token_urlsafe(32)
    token = ExecutorToken(
        name=body.name,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
    )
    repo.create_executor_token(token)

    # Build launch command using request context
    api_url = str(request.base_url).rstrip("/")
    launch_cmd = f'COGOS_API_KEY={raw_token} COGOS_API_URL={api_url} COGOS_COGENT_NAME={name} claude'

    return CreateTokenResponse(
        name=body.name,
        token=raw_token,
        launch_command=launch_cmd,
    )


@router.get("/executor-tokens", response_model=TokensResponse)
def list_tokens(name: str):
    """List all executor tokens (without raw values)."""
    repo = get_repo()
    tokens = repo.list_executor_tokens()
    items = [
        TokenItem(
            name=t.name,
            scope=t.scope,
            created_at=str(t.created_at) if t.created_at else None,
            revoked=t.revoked_at is not None,
        )
        for t in tokens
    ]
    return TokensResponse(tokens=items)


@router.delete("/executor-tokens/{token_name}")
def revoke_token(name: str, token_name: str):
    """Revoke an executor token by name."""
    repo = get_repo()
    revoked = repo.revoke_executor_token(token_name)
    if not revoked:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"ok": True, "name": token_name}
```

**Step 2: Write tests**

**Step 3: Commit**

```bash
git commit -m "feat: add token CRUD endpoints for executor tokens"
```

---

### Task 5: Add token management UI to ExecutorsPanel

**Files:**
- Modify: `dashboard/frontend/src/lib/api.ts` — add token API functions
- Modify: `dashboard/frontend/src/lib/types.ts` — add token types
- Create: `dashboard/frontend/src/components/executors/TokenManager.tsx`
- Modify: `dashboard/frontend/src/components/executors/ExecutorsPanel.tsx` — add TokenManager

**Step 1: Add API functions**

In `dashboard/frontend/src/lib/api.ts`, add:

```typescript
export async function createExecutorToken(cogentName: string, tokenName: string): Promise<{
  name: string;
  token: string;
  launch_command: string;
}> {
  const resp = await fetch(`/api/cogents/${cogentName}/executor-tokens`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ name: tokenName }),
  });
  if (!resp.ok) throw new Error(`Failed to create token: ${resp.statusText}`);
  return resp.json();
}

export async function listExecutorTokens(cogentName: string): Promise<{
  tokens: Array<{ name: string; scope: string; created_at: string | null; revoked: boolean }>;
}> {
  const resp = await fetch(`/api/cogents/${cogentName}/executor-tokens`, { headers: headers() });
  if (!resp.ok) throw new Error(`Failed to list tokens: ${resp.statusText}`);
  return resp.json();
}

export async function revokeExecutorToken(cogentName: string, tokenName: string): Promise<void> {
  const resp = await fetch(`/api/cogents/${cogentName}/executor-tokens/${tokenName}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!resp.ok) throw new Error(`Failed to revoke token: ${resp.statusText}`);
}
```

**Step 2: Create TokenManager component**

Create `dashboard/frontend/src/components/executors/TokenManager.tsx`:

A component that:
- Shows "Create Token" button
- On click, prompts for a name, calls createExecutorToken
- Shows the raw token + launch command in a copyable box (one-time display)
- Lists existing tokens with revoke buttons
- The launch command looks like: `COGOS_API_KEY=<token> COGOS_API_URL=<url> COGOS_COGENT_NAME=<name> claude`

**Step 3: Add TokenManager to ExecutorsPanel**

In `ExecutorsPanel.tsx`, add `<TokenManager cogentName={cogentName} />` at the top of the panel, before the stats grid.

**Step 4: Build and test**

```bash
cd dashboard/frontend && npm run build
```

**Step 5: Commit**

```bash
git commit -m "feat: add token management UI to executors panel"
```

---

### Task 6: Update MCP server .mcp.json and verify end-to-end

**Files:**
- Modify: `.mcp.json`

**Step 1: Verify .mcp.json has correct env vars**

```json
{
  "mcpServers": {
    "cogos": {
      "command": "python",
      "args": ["-m", "cogos.mcp"],
      "env": {
        "COGOS_API_URL": "http://localhost:8102",
        "COGOS_COGENT_NAME": "cogent-1",
        "COGOS_API_KEY": "",
        "COGOS_CHANNELS": "io:claude-code:*,system:alerts"
      }
    }
  }
}
```

The `COGOS_API_KEY` is left empty — the user fills it by creating a token in the dashboard and pasting the launch command.

**Step 2: End-to-end test**

1. Open dashboard → Executors → Create Token
2. Copy the launch command
3. Run it in terminal
4. Verify Claude Code starts, MCP server registers, shows up as idle executor in dashboard
5. Verify channel tools (send, list_channels) work

**Step 3: Commit**

```bash
git commit -m "docs: update .mcp.json for unified token auth"
```
