# Web request handler — runs in Python executor sandbox.
# Capabilities injected: web, file, dir, channels, etc.
# `event` contains the trigger payload including web_request.
# `json` is pre-loaded (no imports allowed).

req = event.get("web_request") or event.get("payload", {}).get("web_request")
if not req:
    print("No web request in event")
    exit()

request_id = event.get("web_request_id") or req.get("request_id", "")
method = req.get("method", "GET")
path = req.get("path", "/")
query = req.get("query", {})
headers = req.get("headers", {})
body = req.get("body")

# Strip /api prefix for routing
route = path.removeprefix("/api").strip("/")

def respond(status, body_content, content_type="application/json"):
    web.respond(
        request_id,
        status=status,
        headers={"content-type": content_type},
        body=body_content,
    )

# ── Routes ───────────────────────────────────────────────────

if route == "status" or route == "":
    respond(200, json.dumps({"status": "ok", "method": method}))

elif route == "files":
    files = web.list()
    respond(200, json.dumps({"files": files.files if hasattr(files, 'files') else []}))

else:
    respond(404, json.dumps({"error": "not found", "path": path}))
