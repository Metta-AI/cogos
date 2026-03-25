# Consolidate CogOS Plugin with fastapi-mcp

**Date:** 2026-03-24
**Goal:** Replace the hand-rolled capability introspection in the CogOS Claude Code plugin with fastapi-mcp on the server, and consolidate the executor-mcp / channel listening into a unified plugin with multiple commands.

## Context

Today there are three overlapping pieces:

| Component | Location | Role |
|-----------|----------|------|
| TypeScript MCP proxy | `claude_code/plugins/cogos/src/server.ts` (945 lines) | Manually introspects CogOS capabilities, builds MCP tools, polls channels |
| Python CogosServer | `src/cogos/mcp/server.py` (356 lines) | HTTP client for executor registration, heartbeat, channel polling |
| Agent SDK executor | `src/cogos/executor/agent_sdk.py` | Builds capability tools for backend executor |

The TypeScript proxy spends ~400 lines on capability introspection and tool building that fastapi-mcp can auto-generate from the OpenAPI spec.

## Architecture

```
┌─────────────────────────────────────────┐
│  CogOS FastAPI Server (app.py)          │
│  + FastApiMCP mounted at /mcp           │
│  ─ auto-exposes ALL endpoints as tools  │
│    from OpenAPI spec                    │
└──────────────────┬──────────────────────┘
                   │ SSE / Streamable HTTP
┌──────────────────┴──────────────────────┐
│  TypeScript MCP proxy (stdio → Claude)  │
│                                         │
│  Responsibilities:                      │
│  ─ Discovery (cogtainers.yml + tokens)  │
│  ─ Browser OAuth + token caching        │
│  ─ Connect/disconnect (switch cogents)  │
│  ─ Proxy tool list from remote /mcp     │
│  ─ Proxy call_tool to remote /mcp       │
│  ─ Channel polling + notifications      │
│  ─ Executor registration + heartbeat    │
└─────────────────────────────────────────┘
```

## Commands

### `/cogos` — List available cogents
- Read `~/.cogos/cogtainers.yml` for known cogtainers
- Read `~/.cogos/tokens.yml` for previously connected cogents
- Present a selection UI showing all options
- On selection, invoke `connect` tool

### `/cogos:cogent` — Connect to a cogent (chat mode)
- Takes optional cogent address argument
- If no arg, falls back to `/cogos` discovery flow
- Connects, loads memory, proxies tools from `/mcp`
- No executor registration, no heartbeat
- Channel polling active (for receiving messages)

### `/cogos:register-executor` — Connect as executor
- Takes optional cogent address argument
- Connects + registers as executor via `POST /api/cogents/{name}/executors/register`
- Starts heartbeat loop (15s interval)
- Subscribes to executor's dedicated channel
- Channel polling active with `notifications/claude/channel`
- Tracks run assignments, supports `complete_run`

## Implementation Steps

### Step 1: Add fastapi-mcp to CogOS server

**Files:** `src/cogos/api/app.py`, `pyproject.toml` (or requirements)

1. Add `fastapi-mcp` dependency
2. Mount in `create_app()`:

```python
from fastapi_mcp import FastApiMCP

def create_app() -> FastAPI:
    app = FastAPI(...)
    # ... existing router setup ...

    # Mount MCP server — exposes all endpoints as tools
    mcp = FastApiMCP(app, name="cogos")
    mcp.mount()  # adds /mcp endpoint

    return app
```

3. Verify: hit `/mcp` endpoint, confirm tools are auto-generated from OpenAPI spec

**Note:** fastapi-mcp respects existing auth (`Depends(verify_dashboard_api_key)`, `Depends(validate_token)`). The proxy will pass auth headers through.

### Step 2: Add MCP SSE client to TypeScript proxy

**Files:** `claude_code/plugins/cogos/package.json`, `claude_code/plugins/cogos/src/server.ts`

1. Add `@modelcontextprotocol/sdk` SSE client dependency (already have the SDK)
2. Create `RemoteMcpClient` class that:
   - Connects to `https://{address}/mcp` via SSE transport
   - Passes auth token as header
   - Can `listTools()` and `callTool(name, args)` against the remote server
   - Supports disconnect/reconnect

### Step 3: Rewrite server.ts as thin proxy

**File:** `claude_code/plugins/cogos/src/server.ts`

Replace the current 945-line file. The new structure:

```typescript
// ── State ──
interface ConnectionState {
  address: string;
  apiUrl: string;
  cogentName: string;
  token: string;
  connected: boolean;
  isExecutor: boolean;
  remoteClient: RemoteMcpClient | null;
}

// ── Local tools (always available) ──
// connect, disconnect

// ── Proxied tools (after connect) ──
// All tools from remote /mcp endpoint, forwarded as-is

// ── Executor tools (after register-executor) ──
// complete_run (could be proxied too if server exposes it)
```

**What gets deleted:**
- `searchCapabilities()` and all capability introspection (~100 lines)
- `invokeCapability()` and type conversion (`pythonTypeToJsonSchema`) (~50 lines)
- `CapabilityTool` interface and `capabilityTools` array
- All `CONNECTED_TOOLS` definitions except channel-related ones
- Dynamic `cogos_<cap>_<method>` tool handling (~30 lines)

**What stays (simplified):**
- `token-cache.ts` — unchanged
- `browserAuthFlow()` — unchanged
- `parseAddress()` — unchanged
- Channel polling (`pollOnce`, `seedSeen`, `startPolling`) — unchanged
- `sendMessage()`, `fetchChannels()`, `fetchMessages()` — unchanged (used by polling)

**What's new:**
- `RemoteMcpClient` — SSE client to remote `/mcp`
- `disconnect()` — tears down connection, clears state, allows reconnect
- `register_executor` tool — calls register API, starts heartbeat
- `ListToolsRequestSchema` handler now merges:
  - Local tools (`connect`, `disconnect`)
  - Remote tools (proxied from `/mcp`)
  - Executor tools (if registered)
- `CallToolRequestSchema` handler routes to:
  - Local handler for `connect`/`disconnect`/`register_executor`
  - Remote client for everything else

### Step 4: Rewrite commands

**File:** `claude_code/plugins/cogos/commands/cogent.md` → update
**New file:** `claude_code/plugins/cogos/commands/cogos.md` (main `/cogos` command)
**New file:** `claude_code/plugins/cogos/commands/register-executor.md`

#### `/cogos` (commands/cogos.md)
```markdown
List available CogOS cogtainers and cogents.

1. Read ~/.cogos/cogtainers.yml for configured cogtainers
2. Read ~/.cogos/tokens.yml for previously connected cogents
3. Present all options to the user
4. On selection, call connect tool with the chosen address
```

#### `/cogos:cogent` (commands/cogent.md)
```markdown
Connect to a CogOS cogent in chat mode.

If argument provided, connect directly.
Otherwise, run the /cogos discovery flow first.

After connecting:
1. Call load_memory (now a proxied remote tool)
2. Follow the cogent's instructions
3. All cogent tools are available via the proxied /mcp
```

#### `/cogos:register-executor` (commands/register-executor.md)
```markdown
Connect to a CogOS cogent as an executor.

If argument provided, connect directly.
Otherwise, run the /cogos discovery flow first.

After connecting:
1. Call register_executor tool
2. Call load_memory
3. Follow the cogent's instructions
4. Channel messages will appear as notifications
5. Use complete_run when assigned tasks are finished
```

### Step 5: Add executor lifecycle to TypeScript proxy

**File:** `claude_code/plugins/cogos/src/server.ts`

Port the executor lifecycle from `src/cogos/mcp/server.py`:

```typescript
async function registerExecutor(): Promise<string> {
  // POST /api/cogents/{name}/executors/register
  // Start heartbeat interval (15s)
  // Subscribe to executor channel
  // Return executor_id
}

async function heartbeat(): Promise<void> {
  // POST /api/cogents/{name}/executors/{id}/heartbeat
  // status: busy if currentRunId, else idle
}
```

The `complete_run` tool is likely already exposed via fastapi-mcp from the runs router. If not, keep the local implementation.

### Step 6: Clean up Python CogosServer

**File:** `src/cogos/mcp/server.py`

This class is still used by the Python executor daemon (`src/cogos/executor/daemon.py`). Don't delete it. But it no longer needs to be the canonical channel polling implementation — the TypeScript proxy owns that for Claude Code sessions.

No changes needed here unless we want to consolidate later.

### Step 7: Test

1. **Server:** Start CogOS API, verify `/mcp` returns tool list
2. **Chat mode:** `/cogos:cogent alpha.softmax-cogents.com` → verify tools load, memory loads, capabilities work
3. **Executor mode:** `/cogos:register-executor alpha.softmax-cogents.com` → verify registration, heartbeat, channel notifications
4. **Switching:** Connect to cogent A, disconnect, connect to cogent B — verify tools refresh
5. **Auth:** Clear token cache, verify browser OAuth flow still works

## Estimated Scope

| Step | Effort | Risk |
|------|--------|------|
| 1. Add fastapi-mcp to server | Small | Low — additive, no existing behavior changes |
| 2. SSE client in TS | Medium | Medium — need to handle SSE reconnection, auth headers |
| 3. Rewrite server.ts | Medium | Medium — core change, but strictly simpler |
| 4. Rewrite commands | Small | Low — just markdown |
| 5. Executor lifecycle in TS | Small | Low — port from working Python code |
| 6. Clean up Python | None | None |
| 7. Test | Medium | — |

## Key Decisions

- **Keep TypeScript** — channel polling works in TS, didn't work in Python
- **Expose everything** — no tag filtering, let the LLM pick relevant tools
- **Keep polling + notifications** — same `notifications/claude/channel` pattern
- **Support cogent switching** — disconnect/reconnect without restarting Claude Code
- **fastapi-mcp on server** — auto-generates tools from OpenAPI, eliminates manual introspection
