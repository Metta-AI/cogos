# Web Publishing Design

## Overview

Let cogents publish web artifacts to their own subdomain (`{name}.softmax-cogents.com`). A cogent can serve static files (HTML/JS/CSS) and handle dynamic API requests — managing its own web presence the same way it manages Discord interactions today.

CogOS provides the infrastructure (IO bridge, capability, serving). The cogent decides what to publish and how to handle requests.

## Separation of Concerns — Three Layers

### Layer 1: AWS Infrastructure (cogtainer CDK stack)

Deployed once per cogent via CloudFormation. These are AWS resources:

| Resource | Purpose |
|----------|---------|
| **Dashboard (FastAPI)** | Already exists. Now also serves cogent web content at `/web/static/` and proxies `/web/api/` requests to the executor. Primary entry point for web content. |
| **Web Gateway Lambda** | Python function + Function URL. Standalone entry point for `{name}.softmax-cogents.com` — validates Cloudflare Access JWT and serves the same content as the dashboard routes. Used when the cogent's subdomain points directly at a Lambda Function URL instead of the ALB. |
| **Cloudflare DNS record** | Points `{name}.softmax-cogents.com` at either the ALB (dashboard) or the Lambda Function URL. Access policy already exists. |

### Layer 2: CogOS Runtime (image boot)

Runs at cogent boot in `init/` scripts, same as Discord channels and capabilities:

| Component | Purpose |
|-----------|---------|
| **`web` capability** | Registered in `init/capabilities.py`. Provides `publish()`, `unpublish()`, `respond()`, `list()`. Same pattern as how the `discord` capability is registered. |
| **`io:web:request` channel** | Created at boot. System channel for inbound HTTP requests. Same as `io:discord:dm`. |

Every cogent gets these automatically. They're CogOS-level concerns baked into the image.

### Layer 3: Cogent Application (optional)

The cogent decides if and how to use its web presence. None of this is mandatory:

| Component | Purpose |
|-----------|---------|
| **Web cog + handler coglet** | Defined in `apps/website/init/cog.py`. A daemon process subscribed to `io:web:request` via `handlers=["io:web:request"]`. |
| **Handler prompt** | The coglet's `main.md` — receives the web request as injected JSON, calls `web.respond()`. Route logic lives here. |
| **Published files** | Any process with the `web` capability can call `web.publish("index.html", content)`. Files sit in file store under `web/`. |

A cogent that doesn't want a web presence just doesn't create a web cog. The infra sits idle at zero cost (no processes running).

### The boundary

The cogent never knows how HTTP serving works. CogOS never knows what the cogent is building.

## Architecture

### Request Flow

There are two entry points that serve the same content:

**Via Dashboard (primary):**
```
Browser
  → ALB → Dashboard (FastAPI)
  → Route decision:
      ├── /web/static/{path}: read file from Postgres file store → return HTTP
      └── /web/api/{path}: append to io:web:request channel → invoke executor → handler responds → return HTTP
```

**Via Web Gateway Lambda (subdomain):**
```
Browser
  → Cloudflare (Access auth via JWT + DNS)
  → Web Gateway Lambda (per-cogent, Function URL)
  → Validate Cloudflare Access JWT
  → Route decision:
      ├── Static: read file from Postgres file store (web/{path}) → return HTTP
      └── Dynamic: append to io:web:request channel → invoke executor → handler responds → return HTTP
```

No Cloudflare caching in v1. Gateway sends `Cache-Control: no-store` on all responses. Caching is a future optimization.

### Components

#### 1. Dashboard Web Routes (new routes on existing FastAPI app)

The dashboard already runs as an ECS service behind the ALB. Two new routes under `/web/` serve cogent web content, completely isolated from the dashboard's own `/api/` namespace:

**`/web/static/{path}` — static content:**
1. Map URL path to file store key: `/web/static/index.html` → `web/index.html`
2. If path is empty or ends with `/`, append `index.html`
3. Read file from Postgres via `FileStore.get_content()`
4. Infer `Content-Type` from extension, default to `application/octet-stream`
5. Return file content, or 404 if not found

**`/web/api/{path}` — dynamic requests:**
1. Find the `io:web:request` channel and its handler process
2. Generate `request_id` (UUID)
3. Append channel message with request payload
4. Invoke executor Lambda synchronously, passing process ID + web request context
5. Return the executor's web response, or 502 on failure

The `/web/` prefix keeps cogent web routes cleanly separated from the dashboard's `/api/cogents/{name}/...` routes, avoiding any routing conflicts.

#### 2. Web Gateway Lambda (new, CogOS)

A standalone Lambda per cogent for the subdomain path. Identical logic to the dashboard routes but runs independently behind a Function URL.

**Auth:** Validates the Cloudflare Access JWT on every request using Cloudflare's public key endpoint (`https://{team}.cloudflareaccess.com/cdn-cgi/access/certs`). Rejects requests without a valid JWT.

**Static path (`/*` except `/api/*`):**
1. Map URL path to file store key: `GET /page.html` → `web/page.html`
2. Lookup chain: `web/{path}` → `web/{path}/index.html` → 404
3. `GET /` → `web/index.html`
4. Read file from Postgres via RDS Data API
5. Infer `Content-Type` from extension, default to `application/octet-stream`
6. Return file content with `Cache-Control: no-store`

**Dynamic path (`/api/*`):** Same flow as dashboard — append channel message, invoke executor, return response.

#### 3. `web` Capability (new, CogOS)

A new built-in capability, analogous to `discord`. Provides the verbs a process needs to interact with the web.

**Methods:**

- `web.publish(path, content)` — write a file to `web/{path}` in the file store. Text content only in v1 (binary files like images are out of scope).
- `web.unpublish(path)` — delete `web/{path}` from the file store.
- `web.respond(request_id, status=200, headers=None, body="")` — set the HTTP response for the current request. Captured by the executor and returned to the caller. Only one `respond()` per `request_id` (subsequent calls are no-ops).
- `web.list(prefix="")` — list published files under `web/{prefix}`.

**Scoping:** Like other capabilities, `web` can be scoped:
- `web.scope(ops=["publish", "list"])` — read/write only, no API handling
- `web.scope(ops=["respond"])` — API handling only, no publishing
- `web.scope(path_prefix="dashboard/")` — restrict to a subdirectory

#### 4. `io:web:request` Channel (new, CogOS)

A system channel created at boot (like `io:discord:dm`). Schema:

```json
{
  "request_id": "string",
  "method": "string",
  "path": "string",
  "query": "object",
  "headers": "object",
  "body": "string | null"
}
```

Handler processes subscribe to this channel to receive dynamic API requests.

Only one process should be subscribed to `io:web:request` at a time. If multiple processes subscribe, each request gets delivered to all subscribers, and the first `web.respond()` call wins (subsequent calls for the same `request_id` are no-ops).

#### 5. Response Mechanism

No intermediate storage needed. The response flows back through the invocation chain:

1. Caller (dashboard or gateway) invokes executor Lambda synchronously
2. Executor runs handler process, injecting the web request as JSON in the user message
3. Handler calls `web.respond(request_id, status, headers, body)`
4. `web.respond()` captures the response in the executor's in-memory `_pending_responses` dict
5. After the handler finishes, the executor extracts the pending response via `_extract_web_response()` and returns it in the `web_response` field
6. Caller returns HTTP

No polling, no correlation tables, no intermediate channels for the response path.

**Error handling:** If the handler process crashes, the executor returns an error payload. The caller returns 502 with error details. If the executor itself times out, the synchronous invoke fails and the caller returns 502/504.

### Dispatch

For dynamic requests, both the dashboard and the gateway bypass the SQS → ingress scheduler path and invoke the executor directly. This is the right choice for synchronous HTTP — web requests shouldn't wait in a scheduler queue.

The channel append (`io:web:request`) still happens for:
- Handler subscription semantics (delivery creation, RUNNABLE marking)
- Audit trail (all requests are logged as channel messages)
- Future: if we add async/webhook-style endpoints, those could use the normal scheduler path

### Request Injection

The executor injects the web request directly into the handler's user message as JSON (via the `web_request` field in the event payload). The handler doesn't need to read from the `io:web:request` channel — the request arrives as part of its input context.

### Concurrency

In v1, the handler process is a single daemon. Concurrent requests are handled as follows:

- If the handler is WAITING (idle), the first request marks it RUNNABLE and it gets dispatched immediately via the executor.
- If the handler is already RUNNING, subsequent requests will invoke the executor, which will dispatch a new run of the same handler process. The executor handles this — it's the same as a daemon being re-woken by a new delivery.
- In practice, LLM-based handlers are slow enough that concurrent requests will queue behind the executor's process dispatch.

This is acceptable for v1. Mitigations:
- The executor timeout prevents unbounded waiting — stale requests get 502'd by the gateway.
- Handlers that do expensive work should respond with 202 and use `procs.spawn()` for async work.
- Future: support multiple handler instances (process pool) for parallelism.

## Infrastructure Details

### Dashboard (FastAPI)

- Already deployed as ECS service behind ALB
- New routes: `/web/static/{path}` (static), `/web/api/{path}` (dynamic)
- Uses `FileStore` and `Repository` from existing dashboard DB connection
- Needs `EXECUTOR_FUNCTION_NAME` env var to invoke the executor Lambda

### Web Gateway Lambda (cogtainer CDK stack)

- Runtime: Python 3.12
- Memory: 256 MB
- Timeout: 60 seconds (must exceed executor timeout)
- Function URL: enabled (provides HTTPS endpoint)
- No VPC — uses RDS Data API like all other Lambdas in the stack
- IAM: RDS Data API access (read file store, write channels), invoke executor Lambda

### Cloudflare DNS + Auth

- Point `{name}.softmax-cogents.com` at the ALB (dashboard) or Lambda Function URL
- Cloudflare Access policy controls who can reach it (already exists for dashboard)
- Gateway Lambda validates Cloudflare Access JWT on every request (public key from `https://{team}.cloudflareaccess.com/cdn-cgi/access/certs`)

### What Doesn't Change

- Executor Lambda / ECS task definitions
- Scheduler, dispatcher, orchestrator Lambdas
- Polis shared infrastructure

## Cogent Usage Example

A cogent publishes a dashboard and handles an API endpoint:

### Publishing static files (in any process with `web` capability)

```python
# Publish a dashboard
web.publish("index.html", "<html>...<script src='app.js'></script>...</html>")
web.publish("app.js", "fetch('/api/status').then(r => r.json()).then(render)")
web.publish("style.css", "body { font-family: sans-serif; }")
```

Accessible at:
- `https://dr-gamma.softmax-cogents.com/web/static/index.html`
- `https://dr-gamma.softmax-cogents.com/web/static/app.js`
- `https://dr-gamma.softmax-cogents.com/web/static/style.css`

### Handling dynamic requests (daemon process subscribed to `io:web:request`)

```python
# The web request is injected into the handler's message as JSON.
# The handler parses it and responds.

if req["path"] == "status":
    data = file.read("data/metrics/latest.json")
    web.respond(req["request_id"], status=200,
                headers={"content-type": "application/json"},
                body=data.content)

elif req["path"].startswith("trigger/"):
    task_name = req["path"].split("/")[-1]
    handle = procs.spawn(name=f"task-{task_name}", content=f"Run {task_name}")
    web.respond(req["request_id"], status=202,
                headers={"content-type": "application/json"},
                body='{"status": "started"}')
```

### Setting up the handler (in image init or cog)

```python
# As a cog (like discord cog) — see apps/website/init/cog.py
cog = add_cog("website")
cog.make_default_coglet(
    entrypoint="main.md",
    mode="daemon",
    files={"main.md": _read("handler/main.md")},
    capabilities=["me", "procs", "dir", "file", "web", "channels", "stdlib",
                   {"name": "dir", "alias": "data", "config": {"prefix": "data/"}}],
    handlers=["io:web:request"],
    priority=5.0,
)
```

## URL Routing

Simple convention-based routing, no configuration needed:

**Via Dashboard:**

| URL Pattern | Behavior |
|-------------|----------|
| `/web/static/` | Serve `web/index.html` from file store |
| `/web/static/{path}` | Serve `web/{path}` from file store, 404 if not found |
| `/web/api/{path}` | Bridge to `io:web:request` channel, invoke executor |

**Via Web Gateway Lambda (subdomain):**

| URL Pattern | Behavior |
|-------------|----------|
| `/` | Serve `web/index.html` |
| `/{path}` | Serve `web/{path}`, then try `web/{path}/index.html`, then 404 |
| `/api/{path}` | Bridge to `io:web:request` channel, invoke executor |

The dashboard routes live under `/web/` to avoid conflicts with the dashboard's own `/api/` namespace. The web gateway Lambda serves at the root since it has no other routes to conflict with.

## Limitations (v1)

- **Text-only static files** — binary content (images, PDFs) not supported via `web.publish()`. Cogents can link to external assets.
- **Serial request handling** — one handler process, requests queue serially. Handlers should respond fast and spawn child processes for expensive work.
- **6 MB payload limit** — Lambda Function URL limit applies to both request and response bodies.
- **No CORS headers** — cogent's frontend JS must be served from the same subdomain to avoid CORS issues. Same-origin requests work without CORS headers.

## What This Doesn't Include (Future)

- **Cloudflare caching** — add `Cache-Control` headers and Cloudflare cache purge on file update
- **WebSocket support** — for real-time push from cogent to browser
- **Multiple route handlers** — different processes for different URL patterns (e.g., `io:web:request:/api/v2/*`)
- **Handler process pool** — multiple instances for concurrent request handling
- **CORS configuration** — cogent-controlled CORS headers for cross-origin use
- **Binary file support** — images, PDFs, etc. via base64 or S3 sidecar
- **Rate limiting** — per-cogent request limits
- **Custom domains** — beyond `{name}.softmax-cogents.com`
