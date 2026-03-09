# GitHub Webhook IO

Receives GitHub webhooks via a Cloudflare Worker, validates HMAC signatures
at the edge, and POSTs normalized events to the cogent's ingest endpoint.
The ingest Lambda inserts into the `events` table via Data API. Processes
subscribe to GitHub events through handlers.

## Architecture

```
Inbound:
  GitHub -> Cloudflare Worker -> HTTPS POST -> Ingest Lambda (Function URL)
         -> INSERT INTO events (status='proposed') via Data API
         -> Scheduler matches handlers -> Process wakes

Outbound:
  Process calls github/post_comment capability -> GitHub REST API -> repo
```

### Why Cloudflare Worker

- HMAC verification at the edge before traffic reaches AWS
- Sub-millisecond cold start — no missed webhooks
- DDoS protection for free
- Single Worker handles all webhook sources (GitHub, Asana, future)
- Free tier covers typical webhook volumes

## Components

### 1. Cloudflare Worker

A route on the shared `cogent-webhooks` Worker. Deployed once for the domain.
GitHub webhook URLs point here:

```
https://webhooks.softmax-cogents.com/github/<cogent-name>
```

The Worker:
1. Extracts the cogent name from the URL path.
2. Reads the raw request body.
3. Verifies `X-Hub-Signature-256` against the webhook secret (per-cogent
   secret stored in Workers KV).
4. Responds to `ping` events with 200 immediately.
5. Transforms the GitHub payload into a normalized event.
6. Looks up the cogent's ingest URL from KV.
7. POSTs to the ingest endpoint with a bearer token.
8. Returns 200 to GitHub.

```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/github\/([a-z0-9.-]+)$/);
    if (!match) return new Response("Not found", { status: 404 });

    const cogentName = match[1];
    const body = await request.arrayBuffer();
    const bodyBytes = new Uint8Array(body);

    // Verify HMAC
    const secret = await env.WEBHOOK_SECRETS.get(`github:${cogentName}`);
    if (!secret) return new Response("Unknown cogent", { status: 404 });

    const signature = request.headers.get("X-Hub-Signature-256") || "";
    if (!await verifyHmac(bodyBytes, signature, secret)) {
      return new Response("Invalid signature", { status: 403 });
    }

    const payload = JSON.parse(new TextDecoder().decode(bodyBytes));
    const ghEvent = request.headers.get("X-GitHub-Event") || "";

    if (ghEvent === "ping") return new Response("pong");

    // Transform to CogOS event
    const action = payload.action || null;
    const eventType = action ? `github:${ghEvent}:${action}` : `github:${ghEvent}`;
    const normalized = extractPayload(ghEvent, action, payload);

    // Look up ingest URL
    const ingestUrl = await env.COGENT_ROUTES.get(cogentName);
    if (!ingestUrl) return new Response("No route", { status: 404 });

    const resp = await fetch(`${ingestUrl}/api/ingest/github`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.INGEST_SECRET}`,
      },
      body: JSON.stringify({
        event_type: eventType,
        source: "io.github",
        payload: normalized,
      }),
    });

    if (!resp.ok) throw new Error(`Ingest failed: ${resp.status}`);
    return new Response("ok");
  },
};
```

### 2. Ingest Lambda

A Lambda with a Function URL, sitting behind Cloudflare (proxied). Validates
the bearer token, inserts into the `events` table via Data API with
`status='proposed'`.

```python
def handler(event, context):
    """Ingest Lambda — receives webhook payloads from CF Worker."""
    body = json.loads(event.get("body", "{}"))
    headers = event.get("headers", {})

    token = headers.get("authorization", "").removeprefix("Bearer ")
    if not _verify_ingest_token(token):
        return {"statusCode": 401}

    repo = get_repo()
    evt = Event(
        event_type=body["event_type"],
        source=body.get("source", "io.github"),
        payload=body.get("payload", {}),
    )
    event_id = repo.append_event(evt, status="proposed")
    return {"statusCode": 200, "body": json.dumps({"event_id": str(event_id)})}
```

This flows into the existing pipeline: Dispatcher Lambda picks up proposed
events, Scheduler matches handlers, processes wake.

### 3. GitHub Sender

Outbound capability for posting comments, reviews, etc. Uses a GitHub token
stored in Secrets Manager (per-cogent).

```python
class GitHubSender:
    def __init__(self, token: str):
        self._token = token
        self._session = None

    def post_comment(self, repo: str, issue_number: int, body: str) -> dict:
        resp = requests.post(
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
            headers={
                "Authorization": f"token {self._token}",
                "Accept": "application/vnd.github+json",
            },
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()
```

### 4. GitHub Capabilities

Registered in `BUILTIN_CAPABILITIES`. Processes interact through proxy
objects in the sandbox:

```python
# In sandbox:
github.post_comment(repo="org/repo", issue_number=42, body="LGTM")
github.search_events(event_type="github:pull_request:opened", limit=5)
```

Capability definitions:

```
github/post_comment
  handler: cogos.io.github.capability.post_comment
  input:   { repo: str, issue_number: int, body: str }
  output:  { id: int, html_url: str }

github/search_events
  handler: cogos.io.github.capability.search_events
  input:   { event_type?: str, repo?: str, limit?: int }
  output:  list[{ event_type, repo, sender, number, title, body, url }]
```

`github/search_events` queries the `events` table for `github:*` events.
No external API call needed — webhooks are already in the database.

```python
def search_events(repo: Repository, process_id: UUID, args: dict) -> CapabilityResult:
    event_type = args.get("event_type", "github:")
    limit = args.get("limit", 20)
    events = repo.get_events(event_type_prefix=event_type, limit=limit)

    results = []
    for e in events:
        p = e.payload
        results.append({
            "event_type": e.event_type,
            "repo": p.get("repository"),
            "sender": p.get("sender"),
            "number": p.get("number"),
            "title": p.get("title"),
            "body": p.get("body"),
            "url": p.get("url"),
        })
    return CapabilityResult(content=results)
```

## Event Type Convention

Event types follow `github:<gh_event>:<action>`. No special mapping table —
handler patterns match directly with glob syntax.

| GitHub Event                      | Action             | CogOS Event Type                                  |
|-----------------------------------|--------------------|----------------------------------------------------|
| `push`                            | —                  | `github:push`                                      |
| `issues`                          | `opened`           | `github:issues:opened`                             |
| `issues`                          | `assigned`         | `github:issues:assigned`                           |
| `issues`                          | `closed`           | `github:issues:closed`                             |
| `issue_comment`                   | `created`          | `github:issue_comment:created`                     |
| `pull_request`                    | `opened`           | `github:pull_request:opened`                       |
| `pull_request`                    | `closed`           | `github:pull_request:closed`                       |
| `pull_request`                    | `review_requested` | `github:pull_request:review_requested`             |
| `pull_request_review`             | `submitted`        | `github:pull_request_review:submitted`             |
| `pull_request_review_comment`     | `created`          | `github:pull_request_review_comment:created`       |
| `check_suite`                     | `completed`        | `github:check_suite:completed`                     |
| `check_run`                       | `completed`        | `github:check_run:completed`                       |
| Other                             | Any                | `github:<event>:<action>`                          |

## Payload Extraction

The Worker extracts a normalized payload from the raw GitHub webhook body.
The full raw body is preserved under `payload.raw` for processes that need it.

```
push        -> ref, commits[0].message, head_commit.url, repository
issues      -> number, title, body, html_url, repository, sender
issue_comment -> number, comment.body, comment.html_url, repository, sender
pull_request -> number, title, body, html_url, head.ref, base.ref, repository, sender
pull_request_review -> number, review.state, review.body, repository, sender
pull_request_review_comment -> number, comment.body, comment.path, comment.line, repository, sender
check_suite -> conclusion, head_branch, repository
check_run   -> conclusion, name, html_url, repository
```

## Handler Examples

```
Handler:
  process: code-reviewer
  event_pattern: "github:pull_request:opened"

Handler:
  process: issue-triage
  event_pattern: "github:issues:opened"

Handler:
  process: ci-fixer
  event_pattern: "github:check_suite:completed"
```

Processes filter further in code — e.g. the ci-fixer checks
`payload.conclusion == "failure"` before acting.

## Worker Secrets (KV)

| Key                          | Value                                           |
|------------------------------|--------------------------------------------------|
| `github:<cogent>`            | HMAC webhook secret for that cogent              |
| `<cogent>` (in COGENT_ROUTES)| Ingest URL, e.g. `https://ovo.softmax-cogents.com` |

Worker environment secrets (via `wrangler secret put`):

| Secret           | Purpose                            |
|------------------|------------------------------------|
| `INGEST_SECRET`  | Bearer token for ingest endpoint   |

## Repo Filtering

Optional. The Worker can check `payload.repository.full_name` against a
per-cogent allow-list stored in KV (`repos:<cogent>` -> comma-separated
`org/repo` strings). If the key doesn't exist, all repos are forwarded.

## CDK Changes

Add to `BrainStack`:

```python
# Ingest Lambda with Function URL
ingest_fn = lambda_.Function(
    self, "IngestLambda",
    function_name=f"cogent-{safe_name}-ingest",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="cogos.io.ingest.handler",
    code=lambda_code,
    memory_size=256,
    timeout=Duration.seconds(10),
    role=ingest_role,  # Data API access only
    environment=env,
)
ingest_fn.add_function_url(
    auth_type=lambda_.FunctionUrlAuthType.NONE,  # CF Worker handles auth via bearer token
)
```

The Function URL is stored in Workers KV as the cogent's ingest route.

## Provisioning CLI

```
cogos io github setup <cogent-name>
  -> Generates a webhook secret
  -> Stores in CF Workers KV (github:<cogent> -> secret)
  -> Stores ingest URL in CF Workers KV (COGENT_ROUTES/<cogent>)
  -> Outputs the webhook URL to configure in GitHub repo settings
  -> Stores GitHub token in Secrets Manager for outbound API calls
```

## Package Structure

```
cogos/io/github/
    design.md           this document
    capability.py       github/post_comment, github/search_events handlers
    sender.py           GitHubSender (REST API outbound)
    worker/
        src/
            index.ts    shared webhook Worker (github route)
            verify.ts   HMAC verification
            transform.ts payload normalization
        wrangler.toml
        package.json

cogos/io/
    ingest.py           shared ingest Lambda (handles /github, /email, etc.)
```

The ingest Lambda is shared across all IO sources. Each source has its own
CF Worker route that transforms and forwards to the same endpoint. The Lambda
validates the bearer token and inserts into events with `status='proposed'`.
