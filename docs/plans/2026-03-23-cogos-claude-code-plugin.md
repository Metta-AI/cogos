# CogOS Claude Code Plugin — Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a Claude Code plugin that lets you connect to any cogent by running `/cogos:cogent <address>`. The plugin provides an MCP server (thin local proxy) that connects to a remote CogOS API SSE/HTTP endpoint, loading the cogent's memory, capabilities, and channels — making the Claude Code session *be* the cogent.

**Architecture:** A Claude Code plugin (`cogos-plugin`) bundles a thin local stdio MCP server and a `/cogos:cogent` slash command. The MCP server proxies to the CogOS API, which serves the cogent's memory, dynamically-discovered capabilities as individual MCP tools, and channel operations. Auth uses existing executor tokens with a browser-based flow. The existing TS MCP server (`channels/claude-code/server.ts`) is preserved for direct executor use.

**Tech Stack:** TypeScript MCP server (matches existing `server.ts`, good MCP SDK), Claude Code plugin system, existing CogOS dashboard API.

---

## Architecture Overview

```
┌──────────────┐   stdio    ┌───────────────────┐   HTTP    ┌──────────────┐
│  Claude Code  │◄──────────►│  cogos MCP plugin  │◄─────────►│  CogOS API   │
│               │            │  (thin local proxy)│           │              │
└──────────────┘            └───────────────────┘           └──────┬───────┘
                                    │                              │
                              ~/.cogos/tokens.yml           ┌──────┴──────┐
                                                            │ Memory      │
                                                            │ Capabilities│
                                                            │ Channels    │
                                                            └─────────────┘
```

**Flow:**
1. User installs plugin: `/plugin install cogos`
2. User types: `/cogos:cogent alpha.softmax-cogents.com`
3. Plugin checks `~/.cogos/tokens.yml` for cached token
4. If no token: opens `https://alpha.softmax-cogents.com/token-auth` in browser
5. User picks a token from the dashboard (if logged in) → token returned via callback
6. Token cached locally
7. MCP server connects to `https://alpha.softmax-cogents.com/api/cogents/{name}/...`
8. Loads cogent identity prompt, exposes `load_memory`, `search_capabilities`, channels
9. Claude Code becomes the cogent

## Components

### 1. Claude Code Plugin Structure

```
cogos-plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json                    # MCP server config
├── commands/
│   └── cogent.md                # /cogos:cogent slash command
├── src/
│   └── server.ts                # Thin MCP proxy server
├── package.json
└── tsconfig.json
```

**plugin.json:**
```json
{
  "name": "cogos",
  "version": "1.0.0",
  "description": "Connect Claude Code to CogOS cogents",
  "author": { "name": "Softmax" },
  "repository": "https://github.com/softmax-ai/cogos-claude-code-plugin"
}
```

**.mcp.json:**
```json
{
  "mcpServers": {
    "cogos": {
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/dist/server.js"],
      "env": {}
    }
  }
}
```

### 2. MCP Server (Thin Local Proxy)

The local MCP server starts with minimal tools and dynamically expands when connected to a cogent.

**Initial tools (before connect):**
- `connect` — Connect to a cogent (address + optional token)

**After connect:**
- `load_memory` — Fetch cogent's full rendered memory from ContextEngine
- `search_capabilities` — Search available capability methods by keyword
- `list_channels` / `send` / `reply` — Channel operations
- `complete_run` — Signal run completion
- Dynamic capability tools discovered via `search_capabilities`

**On connect, the server:**
1. Resolves auth (cached token or browser flow)
2. Fetches cogent identity and sets MCP `instructions` prompt
3. Sends `list_changed` notification so Claude Code discovers new tools
4. Starts heartbeat loop (optional, for presence)
5. Starts channel poll loop (forwards as `notifications/claude/channel`)

### 3. Token Auth Flow

**Browser-based:**
1. MCP server opens `https://{address}/token-auth` in default browser
2. Dashboard page shows available API tokens for the cogent (if user has dashboard access)
3. User selects a token
4. Page redirects to `http://localhost:{random_port}/callback?token={token}`
5. MCP server captures token, caches in `~/.cogos/tokens.yml`

**Token cache (`~/.cogos/tokens.yml`):**
```yaml
tokens:
  alpha.softmax-cogents.com:
    token: "sk-..."
    cogent_name: "alpha"
    cached_at: "2026-03-23T..."
```

**Dashboard changes:**
- **API Tokens → Configure section** (not under Executors)
- Each token has a `[cc]` badge → menu copies `/cogos:cogent {address}` command
- Tokens are revocable from Configure

### 4. `/cogos:cogent` Slash Command

**`commands/cogent.md`:**
```markdown
---
description: Connect to a CogOS cogent
---

Connect to a CogOS cogent using the cogos MCP server. Call the `connect` tool
with the provided cogent address. If a token is needed, the auth flow will
open in the browser.

After connecting, call `load_memory` to load the cogent's full instructions
and context. Then use `search_capabilities` to discover available tools.
```

### 5. Capability Discovery (Lazy)

Instead of loading all capabilities upfront (which could be 100+ tools):

1. `search_capabilities(query)` calls API: `GET /api/cogents/{name}/capabilities?q={query}`
2. Returns matching capability methods with descriptions
3. Server registers matched methods as MCP tools
4. Sends `list_changed` notification
5. Claude Code can now call them directly

Tool naming: `cogos_{capability}_{method}` (e.g. `cogos_file_read`, `cogos_discord_send_message`)

### 6. New API Endpoints

**Memory endpoint (new):**
- `GET /api/cogents/{name}/memory/rendered` — Returns full rendered memory from ContextEngine
  - Returns: `{ "prompt": "...", "layers": [...] }`

**Token auth page (new):**
- `GET /api/cogents/{name}/token-auth` — Serves a page to select/copy an API token
- `GET /api/cogents/{name}/token-auth/callback` — Returns selected token (for local server callback)

**Existing endpoints used:**
- `GET /api/cogents/{name}/channels` — List channels
- `POST /api/cogents/{name}/channels/{id}/messages` — Send message
- `GET /api/cogents/{name}/channels/{id}` — Get messages
- `GET /api/v1/capabilities` — List capabilities
- `GET /api/v1/capabilities/{name}/methods` — List capability methods
- `POST /api/v1/capabilities/{name}/{method}` — Invoke capability method

### 7. Plugin Marketplace

Distributed via GitHub-based marketplace:

```
softmax-ai/cogos-marketplace/
├── marketplace.json
└── plugins/
    └── cogos/
        └── (plugin source or pointer to repo)
```

**marketplace.json:**
```json
{
  "plugins": [{
    "name": "cogos",
    "version": "1.0.0",
    "description": "Connect Claude Code to CogOS cogents",
    "source": {
      "source": "github",
      "repo": "softmax-ai/cogos-claude-code-plugin"
    }
  }]
}
```

**Install:**
```bash
# One-time: add marketplace
/plugin marketplace add softmax-ai/cogos-marketplace

# Install
/plugin install cogos
```

---

## Implementation Tasks

### Task 1: Create plugin scaffold and MCP server with `connect` tool

Create the plugin directory structure with `plugin.json`, `.mcp.json`, `package.json`, `tsconfig.json`, and the base MCP server in `src/server.ts`.

**Files:**
- Create: `plugins/cogos/.claude-plugin/plugin.json`
- Create: `plugins/cogos/.mcp.json`
- Create: `plugins/cogos/package.json`
- Create: `plugins/cogos/tsconfig.json`
- Create: `plugins/cogos/src/server.ts`

The server should:
- Start with a single `connect` tool
- Accept `address` and optional `token` parameters
- Store connection state (api_url, cogent_name, token)
- On connect: validate by fetching `/api/cogents/{name}/status` or similar health check
- After connect: register channel/memory/capability tools and send `list_changed`

**Commit:** `feat: scaffold cogos Claude Code plugin with connect tool`

---

### Task 2: Add token auth with browser flow and local cache

Implement the browser-based auth flow in the MCP server:
- If no token provided to `connect`, check `~/.cogos/tokens.yml`
- If no cached token, start a local HTTP server on a random port
- Open `https://{address}/token-auth?callback=http://localhost:{port}/callback` in browser
- Wait for callback with token
- Cache token in `~/.cogos/tokens.yml`

**Files:**
- Modify: `plugins/cogos/src/server.ts` — add auth flow
- Create: `plugins/cogos/src/token-cache.ts` — YAML token cache read/write

**Commit:** `feat: add browser-based token auth flow to cogos plugin`

---

### Task 3: Add memory loading and MCP prompt/instructions

After connect:
- Fetch rendered memory from `GET /api/cogents/{name}/memory/rendered`
- Set MCP server `instructions` to short identity text
- Expose `load_memory` tool that returns the full rendered prompt

**API side (if endpoint doesn't exist):**
- Add `GET /api/cogents/{name}/memory/rendered` to dashboard API
- Uses ContextEngine to build and return the full system prompt

**Files:**
- Modify: `plugins/cogos/src/server.ts` — add `load_memory` tool
- Modify: `src/dashboard/routers/` — add memory endpoint if needed

**Commit:** `feat: add load_memory tool and rendered memory API endpoint`

---

### Task 4: Add capability discovery and dynamic tool registration

Implement lazy capability discovery:
- `search_capabilities(query)` tool calls the capabilities API
- Matched methods are registered as individual MCP tools
- Send `list_changed` notification after registration
- Capability invocation proxied to `POST /api/v1/capabilities/{cap}/{method}`

Reuse the existing capability proxy endpoints from `src/cogos/api/routers/capabilities.py`.

**Files:**
- Modify: `plugins/cogos/src/server.ts` — add `search_capabilities` and dynamic tool registration

**Commit:** `feat: add lazy capability discovery to cogos plugin`

---

### Task 5: Add channel operations and polling

Port channel tools from existing `server.ts`:
- `list_channels`, `send`, `reply`, `complete_run`
- Channel poll loop with `notifications/claude/channel`
- Seen message deduplication

**Files:**
- Modify: `plugins/cogos/src/server.ts` — add channel tools and polling

**Commit:** `feat: add channel operations and polling to cogos plugin`

---

### Task 6: Add `/cogos:cogent` slash command

Create the slash command that triggers the connect flow.

**Files:**
- Create: `plugins/cogos/commands/cogent.md`

**Commit:** `feat: add /cogos:cogent slash command`

---

### Task 7: Dashboard — move API tokens to Configure, add [cc] badge

**Dashboard backend:**
- Token CRUD endpoints already exist (from unify-api-tokens plan)
- Ensure they're under a "configure" conceptual grouping

**Dashboard frontend:**
- Move token management UI from ExecutorsPanel to a new ConfigurePanel (or Settings section)
- Add `[cc]` badge to each token that opens a menu
- Menu copies `/cogos:cogent {address}` command to clipboard

**Files:**
- Modify: `dashboard/frontend/src/components/` — reorganize token UI
- Create: `dashboard/frontend/src/components/configure/TokenManager.tsx`

**Commit:** `feat: move API tokens to Configure section with [cc] badge`

---

### Task 8: Add token-auth page to dashboard

Create a simple page at `/token-auth` that:
- Shows available API tokens (names only, not values)
- Lets user select one
- If `callback` query param present, redirects with token
- If no callback, copies token to clipboard

**Files:**
- Create: `dashboard/frontend/src/app/token-auth/page.tsx`
- Modify: `src/dashboard/routers/` — add token-auth API support if needed

**Commit:** `feat: add token-auth page for browser-based auth flow`

---

### Task 9: Set up plugin marketplace

Create the GitHub-based marketplace repository structure.

**Files:**
- Create: `marketplace/marketplace.json`
- Create: `marketplace/README.md`

Or create as a separate repo `softmax-ai/cogos-marketplace`.

**Commit:** `feat: set up cogos plugin marketplace`

---

### Task 10: Add rendered memory API endpoint

Add the endpoint that the plugin's `load_memory` tool calls.

**Files:**
- Modify: `src/dashboard/routers/` — add new router or endpoint
- The endpoint should:
  1. Accept cogent name from path
  2. Accept optional `program_name` query param (defaults to loading all memory)
  3. Use ContextEngine + MemoryStore to build the rendered prompt
  4. Return `{ "prompt": "...", "layers": [{ "name": "...", "content": "...", "priority": N }] }`

**Commit:** `feat: add rendered memory API endpoint`

---

## Notes

- The existing TS MCP server (`channels/claude-code/server.ts`) is preserved — it's used when Claude Code runs as a full executor (registered, accepting work). The new plugin is for interactive "be the cogent" sessions.
- The plugin's MCP server is intentionally thin — all real logic (memory resolution, capability execution, channel routing) lives in the CogOS API.
- The `search_capabilities` → dynamic tool pattern uses MCP's `list_changed` notification, which Claude Code supports natively.
- Token auth reuses existing executor tokens — no new auth system needed.
