# newsfromthefront Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `newsfromthefront` competitive analysis cogent — a CogOS application that daily searches Perplexity, GitHub, and Twitter for competitive intelligence, posts delta reports to Discord, and learns from user feedback via thread replies.

**Architecture:** Three layers: (1) `web_search` capability wraps Perplexity, GitHub Search API, and X API v2 as a reusable CogOS primitive; (2) an image at `images/apps/newsfromthefront/` defines channels, schemas, and four daemon processes; (3) `discord-handle-message` in `cogent-v1` is updated to route report thread replies to the analyst.

**Tech Stack:** Python (capabilities), CogOS image DSL (init scripts), Markdown (agent prompts), Perplexity sonar API, GitHub REST API v3, X API v2

**Spec:** `docs/superpowers/specs/2026-03-12-newsfromthefront-design.md`

---

## File Map

**New files:**
- `src/cogos/capabilities/web_search.py` — WebSearchCapability (Perplexity + GitHub + X)
- `tests/cogos/capabilities/test_web_search.py` — unit tests for above
- `images/apps/newsfromthefront/init/capabilities.py` — register all builtins
- `images/apps/newsfromthefront/init/resources.py` — lambda_slots pool
- `images/apps/newsfromthefront/init/cron.py` — daily 08:00 UTC cron
- `images/apps/newsfromthefront/init/processes.py` — schemas, channels, all four processes
- `images/apps/newsfromthefront/files/whoami/index.md` — agent identity
- `images/apps/newsfromthefront/files/newsfromthefront/researcher.md` — researcher prompt
- `images/apps/newsfromthefront/files/newsfromthefront/analyst.md` — analyst prompt
- `images/apps/newsfromthefront/files/newsfromthefront/test.md` — test process prompt
- `images/apps/newsfromthefront/files/newsfromthefront/backfill.md` — backfill prompt
- `images/cogent-v1/files/cogos/lib/discord-handle-message.md` — extracted prompt for discord-handle-message

**Modified files:**
- `src/cogos/capabilities/__init__.py` — add web_search entry to BUILTIN_CAPABILITIES
- `images/cogent-v1/init/processes.py` — convert discord-handle-message to use code_key + add thread routing

---

## Chunk 1: `web_search` Capability

### Task 1: Create test file with failing tests

**Files:**
- Create: `tests/cogos/capabilities/test_web_search.py`

- [ ] **Step 1.1: Write the test file**

```python
"""Tests for WebSearchCapability."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.web_search import (
    GithubSearchResult,
    SearchError,
    SearchResult,
    TwitterSearchResult,
    WebSearchCapability,
)


@pytest.fixture
def cap():
    return WebSearchCapability(MagicMock(), uuid4())


class TestSearch:
    def test_returns_summary_and_sources(self, cap):
        resp = {
            "choices": [{"message": {"content": "Here is a summary."}}],
            "citations": ["https://example.com"],
        }
        with patch.object(cap, "_get_secret", return_value="key"), \
             patch.object(cap, "_http_json", return_value=resp):
            result = cap.search("competitor analysis")
        assert isinstance(result, SearchResult)
        assert result.summary == "Here is a summary."
        assert result.sources[0]["url"] == "https://example.com"

    def test_passes_recency_to_payload(self, cap):
        resp = {"choices": [{"message": {"content": "s"}}], "citations": []}
        with patch.object(cap, "_get_secret", return_value="k"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search("query", recency="day")
        payload = mock_http.call_args[1]["payload"]
        assert payload["search_recency_filter"] == "day"

    def test_passes_date_filter_for_backfill(self, cap):
        resp = {"choices": [{"message": {"content": "s"}}], "citations": []}
        with patch.object(cap, "_get_secret", return_value="k"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search("q", after_date="2025-01-01", before_date="2025-01-31")
        payload = mock_http.call_args[1]["payload"]
        assert payload["search_date_filter"] == {"after": "2025-01-01", "before": "2025-01-31"}

    def test_returns_error_on_exception(self, cap):
        with patch.object(cap, "_get_secret", side_effect=Exception("no key")):
            result = cap.search("query")
        assert isinstance(result, SearchError)
        assert "no key" in result.error

    def test_scope_blocks_disallowed_op(self, cap):
        scoped = cap.scope(ops=["search_github"])
        with pytest.raises(PermissionError):
            scoped._check("search")

    def test_scope_allows_permitted_op(self, cap):
        scoped = cap.scope(ops=["search", "search_github"])
        scoped._check("search")  # should not raise


class TestSearchGithub:
    def test_returns_items(self, cap):
        resp = {
            "items": [{
                "full_name": "org/repo",
                "html_url": "https://github.com/org/repo",
                "description": "A tool",
                "stargazers_count": 42,
                "updated_at": "2026-01-01",
            }]
        }
        with patch.object(cap, "_get_secret", return_value="tok"), \
             patch.object(cap, "_http_json", return_value=resp):
            result = cap.search_github("competitive analysis tool")
        assert isinstance(result, GithubSearchResult)
        assert result.items[0]["title"] == "org/repo"
        assert result.items[0]["stars"] == 42

    def test_appends_after_date_qualifier(self, cap):
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value={"items": []}) as mock_http:
            cap.search_github("my query", after_date="2025-01-01")
        url = mock_http.call_args[0][0]
        assert "2025-01-01" in url

    def test_defaults_to_repositories_type(self, cap):
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value={"items": []}) as mock_http:
            cap.search_github("query")
        url = mock_http.call_args[0][0]
        assert "/repositories?" in url

    def test_returns_error_on_exception(self, cap):
        with patch.object(cap, "_get_secret", side_effect=Exception("boom")):
            result = cap.search_github("query")
        assert isinstance(result, SearchError)


class TestSearchTwitter:
    def test_returns_tweets_with_author(self, cap):
        resp = {
            "data": [{
                "id": "123",
                "text": "hello world",
                "author_id": "u1",
                "created_at": "2026-01-01T00:00:00Z",
                "public_metrics": {"like_count": 5, "retweet_count": 2},
            }],
            "includes": {"users": [{"id": "u1", "username": "alice"}]},
        }
        with patch.object(cap, "_get_secret", return_value="bearer"), \
             patch.object(cap, "_http_json", return_value=resp):
            result = cap.search_twitter("competitive analysis")
        assert isinstance(result, TwitterSearchResult)
        assert result.tweets[0]["author"] == "alice"
        assert result.tweets[0]["likes"] == 5

    def test_uses_all_endpoint_for_date_range(self, cap):
        resp = {"data": [], "includes": {}}
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search_twitter("q", after_date="2025-01-01")
        assert "/search/all" in mock_http.call_args[0][0]

    def test_uses_recent_endpoint_without_dates(self, cap):
        resp = {"data": [], "includes": {}}
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search_twitter("q")
        assert "/search/recent" in mock_http.call_args[0][0]

    def test_excludes_retweets_from_query(self, cap):
        resp = {"data": [], "includes": {}}
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search_twitter("my topic")
        url = mock_http.call_args[0][0]
        assert "-is%3Aretweet" in url or "-is:retweet" in url

    def test_returns_error_on_exception(self, cap):
        with patch.object(cap, "_get_secret", side_effect=Exception("x")):
            result = cap.search_twitter("q")
        assert isinstance(result, SearchError)
```

- [ ] **Step 1.2: Run tests to confirm they fail (module not found)**

```bash
pytest tests/cogos/capabilities/test_web_search.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'cogos.capabilities.web_search'`

---

### Task 2: Implement WebSearchCapability

**Files:**
- Create: `src/cogos/capabilities/web_search.py`

- [ ] **Step 2.1: Check secrets.py for the boto3 pattern**

```bash
cat src/cogos/capabilities/secrets.py
```
Note the exact boto3 call pattern used. Mirror it in `_get_secret` below.

- [ ] **Step 2.2: Write the capability**

```python
"""WebSearch capability — Perplexity, GitHub, and Twitter/X search."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

ALL_OPS = {"search", "search_github", "search_twitter"}


class SearchResult(BaseModel):
    summary: str
    sources: list[dict[str, str]]


class GithubSearchResult(BaseModel):
    items: list[dict[str, Any]]


class TwitterSearchResult(BaseModel):
    tweets: list[dict[str, Any]]


class SearchError(BaseModel):
    error: str


class WebSearchCapability(Capability):
    """Multi-backend web search: Perplexity (general web), GitHub, Twitter/X."""

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict[str, Any] = {}
        old_ops = set(existing.get("ops") or ALL_OPS)
        new_ops = set(requested.get("ops") or ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(
                f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})"
            )

    def _get_secret(self, key: str) -> str:
        """Fetch a secret from AWS Secrets Manager.

        Mirrors the pattern in src/cogos/capabilities/secrets.py.
        """
        import boto3  # local import — not available in test environments without mock
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=key)
        val = response.get("SecretString", "")
        try:
            parsed = json.loads(val)
            return parsed.get("value", val)
        except (json.JSONDecodeError, AttributeError):
            return val

    def _http_json(
        self,
        url: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request and return parsed JSON. Raises on error."""
        headers = headers or {}
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def search(
        self,
        query: str,
        recency: str | None = None,
        after_date: str | None = None,
        before_date: str | None = None,
    ) -> SearchResult | SearchError:
        """Search the web via Perplexity sonar. recency: 'day'|'week'|'month'."""
        self._check("search")
        try:
            api_key = self._get_secret("cogent/perplexity_api_key")
            payload: dict[str, Any] = {
                "model": "sonar",
                "messages": [{"role": "user", "content": query}],
            }
            if recency:
                payload["search_recency_filter"] = recency
            if after_date or before_date:
                date_filter: dict[str, str] = {}
                if after_date:
                    date_filter["after"] = after_date
                if before_date:
                    date_filter["before"] = before_date
                payload["search_date_filter"] = date_filter
            result = self._http_json(
                "https://api.perplexity.ai/chat/completions",
                payload=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            summary = result["choices"][0]["message"]["content"]
            sources = [
                {"url": url, "title": "", "snippet": ""}
                for url in result.get("citations", [])
            ]
            return SearchResult(summary=summary, sources=sources)
        except Exception as e:
            logger.exception("Perplexity search failed")
            return SearchError(error=str(e))

    def search_github(
        self,
        query: str,
        type: str = "repositories",
        after_date: str | None = None,
        before_date: str | None = None,
    ) -> GithubSearchResult | SearchError:
        """Search GitHub. type: 'repositories'|'issues'|'discussions'|'code'."""
        self._check("search_github")
        try:
            token = self._get_secret("cogent/github_token")
            full_query = query
            if after_date:
                full_query += f" pushed:>{after_date}"
            if before_date:
                full_query += f" pushed:<{before_date}"
            params = urllib.parse.urlencode({
                "q": full_query,
                "per_page": 30,
                "sort": "updated",
            })
            url = f"https://api.github.com/search/{type}?{params}"
            result = self._http_json(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            items = []
            for item in result.get("items", []):
                items.append({
                    "title": item.get("full_name") or item.get("title") or item.get("name", ""),
                    "url": item.get("html_url", ""),
                    "description": (item.get("description") or "")[:300],
                    "stars": item.get("stargazers_count"),
                    "updated_at": item.get("updated_at", ""),
                })
            return GithubSearchResult(items=items)
        except Exception as e:
            logger.exception("GitHub search failed")
            return SearchError(error=str(e))

    def search_twitter(
        self,
        query: str,
        recency: str | None = None,
        after_date: str | None = None,
        before_date: str | None = None,
    ) -> TwitterSearchResult | SearchError:
        """Search Twitter/X via X API v2."""
        self._check("search_twitter")
        try:
            bearer = self._get_secret("cogent/twitter_bearer_token")
            params: dict[str, Any] = {
                "query": query + " -is:retweet",
                "max_results": 100,
                "tweet.fields": "created_at,public_metrics,author_id",
                "expansions": "author_id",
                "user.fields": "username",
            }
            if after_date:
                params["start_time"] = after_date + "T00:00:00Z"
            if before_date:
                params["end_time"] = before_date + "T23:59:59Z"
            # /all for historical range queries, /recent for live search
            endpoint = "all" if (after_date or before_date) else "recent"
            url = (
                f"https://api.twitter.com/2/tweets/search/{endpoint}?"
                + urllib.parse.urlencode(params)
            )
            result = self._http_json(
                url,
                headers={"Authorization": f"Bearer {bearer}"},
            )
            users = {
                u["id"]: u["username"]
                for u in result.get("includes", {}).get("users", [])
            }
            tweets = []
            for t in result.get("data", []):
                metrics = t.get("public_metrics", {})
                tweets.append({
                    "id": t["id"],
                    "text": t["text"],
                    "author": users.get(t.get("author_id", ""), "unknown"),
                    "url": f"https://twitter.com/i/web/status/{t['id']}",
                    "created_at": t.get("created_at", ""),
                    "likes": metrics.get("like_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                })
            return TwitterSearchResult(tweets=tweets)
        except Exception as e:
            logger.exception("Twitter search failed")
            return SearchError(error=str(e))

    def __repr__(self) -> str:
        return "<WebSearchCapability search() search_github() search_twitter()>"
```

- [ ] **Step 2.3: Run tests — expect all to pass**

```bash
pytest tests/cogos/capabilities/test_web_search.py -v
```
Expected: all green.

- [ ] **Step 2.4: Commit**

```bash
git add src/cogos/capabilities/web_search.py tests/cogos/capabilities/test_web_search.py
git commit -m "feat(capabilities): add web_search capability (Perplexity, GitHub, X API)"
```

---

### Task 3: Register `web_search` in BUILTIN_CAPABILITIES

**Files:**
- Modify: `src/cogos/capabilities/__init__.py`

- [ ] **Step 3.1: Add entry to BUILTIN_CAPABILITIES list**

Add after the `"schemas"` entry (end of list):

```python
    {
        "name": "web_search",
        "description": "Multi-backend web search: Perplexity (general web), GitHub (repos/issues/code), Twitter/X (tweets).",
        "handler": "cogos.capabilities.web_search.WebSearchCapability",
        "instructions": (
            "Use web_search to research topics across multiple sources.\n"
            "- web_search.search(query, recency?, after_date?, before_date?) — general web search via Perplexity; recency: 'day'|'week'|'month'\n"
            "- web_search.search_github(query, type?, after_date?, before_date?) — GitHub search; type: 'repositories'|'issues'|'discussions'|'code'\n"
            "- web_search.search_twitter(query, recency?, after_date?, before_date?) — Twitter/X tweet search via X API v2\n"
            "Use recency='day' for latest news. Use after_date/before_date (ISO date strings) for backfill."
        ),
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["search", "search_github", "search_twitter"],
                        },
                    },
                },
            },
        },
    },
```

- [ ] **Step 3.2: Verify existing capability tests still pass**

```bash
pytest tests/cogos/capabilities/ -v
```
Expected: all green.

- [ ] **Step 3.3: Commit**

```bash
git add src/cogos/capabilities/__init__.py
git commit -m "feat(capabilities): register web_search in BUILTIN_CAPABILITIES"
```

---

## Chunk 2: Image Init Files

### Task 4: Create image directory structure and init files

**Files:**
- Create: `images/apps/newsfromthefront/init/capabilities.py`
- Create: `images/apps/newsfromthefront/init/resources.py`
- Create: `images/apps/newsfromthefront/init/cron.py`
- Create: `images/apps/newsfromthefront/init/processes.py`

- [ ] **Step 4.1: Check `add_cron` param name after channels migration**

```bash
grep -n "def add_cron\|event_type" src/cogos/image/spec.py | head -10
```
Confirm whether `add_cron` still uses `event_type=` or was renamed to `channel=` in the migration. The authoritative signature is in `spec.py`. Use whichever param name the function definition shows.

- [ ] **Step 4.2: Create `init/capabilities.py`**

```python
from cogos.capabilities import BUILTIN_CAPABILITIES

for cap in BUILTIN_CAPABILITIES:
    add_capability(
        cap["name"],
        handler=cap["handler"],
        description=cap.get("description", ""),
        instructions=cap.get("instructions", ""),
        schema=cap.get("schema"),
    )
```

- [ ] **Step 4.3: Create `init/resources.py`**

```python
add_resource(
    "lambda_slots",
    type="pool",
    capacity=5,
    metadata={"description": "Concurrent Lambda executor slots"},
)
```

- [ ] **Step 4.4: Create `init/cron.py`**

```python
# Daily research run at 08:00 UTC.
# event_type maps to the channel name that receives the tick message.
# Verify param name against src/cogos/image/apply.py (see Step 4.1).
add_cron("0 8 * * *", event_type="newsfromthefront:tick", payload={}, enabled=True)
```

- [ ] **Step 4.5: Create `init/processes.py`**

```python
# ── Schemas ───────────────────────────────────────────────────────────────────

add_schema("newsfromthefront_findings_ready", definition={
    "fields": {
        "run_id":       "string",
        "findings_key": "string",
        "date":         "string",
        "is_test":      "bool",
        "is_backfill":  "bool",
    },
})

add_schema("newsfromthefront_discord_feedback", definition={
    "fields": {
        "thread_id": "string",
        "content":   "string",
        "author":    "string",
    },
})

add_schema("newsfromthefront_run_requested", definition={
    "fields": {
        # mode: "test" | "backfill"
        "mode":        "string",
        # after_date / before_date: ISO date string, or "" if not applicable
        "after_date":  "string",
        "before_date": "string",
    },
})

# ── Channels ──────────────────────────────────────────────────────────────────

add_channel("newsfromthefront:tick",             channel_type="named")
add_channel("newsfromthefront:findings-ready",   schema="newsfromthefront_findings_ready")
add_channel("newsfromthefront:discord-feedback", schema="newsfromthefront_discord_feedback")
add_channel("newsfromthefront:run-requested",    schema="newsfromthefront_run_requested")

# ── Processes ─────────────────────────────────────────────────────────────────

# Check the Bedrock console or existing deployed process model IDs before
# deploying. Replace the haiku model ID below with the correct region-prefixed
# ID for the model you want each process to use.
_HAIKU  = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_SONNET = "us.anthropic.claude-sonnet-4-6-20251101-v1:0"  # verify this ID

add_process(
    "newsfromthefront-researcher",
    mode="daemon",
    code_key="newsfromthefront/researcher",
    runner="lambda",
    model=_SONNET,
    priority=15.0,
    capabilities=["web_search", "dir", "channels", "secrets"],
    handlers=["newsfromthefront:tick"],
)

add_process(
    "newsfromthefront-analyst",
    mode="daemon",
    code_key="newsfromthefront/analyst",
    runner="lambda",
    model=_SONNET,
    priority=15.0,
    capabilities=["dir", "channels", "discord", "secrets"],
    handlers=["newsfromthefront:findings-ready", "newsfromthefront:discord-feedback"],
)

add_process(
    "newsfromthefront-test",
    mode="daemon",
    code_key="newsfromthefront/test",
    runner="lambda",
    model=_SONNET,
    priority=20.0,
    capabilities=["web_search", "dir", "channels", "discord", "secrets"],
    handlers=["newsfromthefront:run-requested"],
)

add_process(
    "newsfromthefront-backfill",
    mode="daemon",
    code_key="newsfromthefront/backfill",
    runner="lambda",
    model=_HAIKU,
    priority=5.0,
    capabilities=["web_search", "dir", "channels", "discord", "secrets"],
    handlers=["newsfromthefront:run-requested"],
)
```

- [ ] **Step 4.6: Verify image loads without errors**

```bash
python - <<'EOF'
from pathlib import Path
from cogos.image.spec import load_image
spec = load_image(Path("images/apps/newsfromthefront"))
print(f"capabilities: {len(spec.capabilities)}")
print(f"resources:    {len(spec.resources)}")
print(f"channels:     {len(spec.channels)}")
print(f"schemas:      {len(spec.schemas)}")
print(f"processes:    {len(spec.processes)}")
print(f"cron_rules:   {len(spec.cron_rules)}")
EOF
```
Expected output (capability count matches BUILTIN_CAPABILITIES length):
```
capabilities: 12
resources:    1
channels:     4
schemas:      3
processes:    4
cron_rules:   1
```

- [ ] **Step 4.7: Commit**

```bash
git add images/apps/newsfromthefront/
git commit -m "feat(newsfromthefront): add image init files — schemas, channels, processes, cron"
```

---

## Chunk 3: Agent Prompt Files

All files live under `images/apps/newsfromthefront/files/`. They are loaded as the `code_key` content for each process — the LLM sees this as its system context alongside the injected channel message payload.

### Task 5: Write `whoami/index.md`

**Files:**
- Create: `images/apps/newsfromthefront/files/whoami/index.md`

- [ ] **Step 5.1: Write the file**

```markdown
# newsfromthefront

You are the newsfromthefront competitive intelligence agent. Your purpose is to
monitor the competitive landscape for a software project, surface what's new,
and keep the project owner informed via daily Discord reports.

You have four processes:

- **researcher** — wakes daily, reads the project brief, searches Perplexity/GitHub/Twitter, writes findings
- **analyst** — wakes on new findings, compares to knowledge base, writes delta reports, posts to Discord
- **test** — on-demand full loop for tuning, never touches production state
- **backfill** — fills in historical knowledge base one interval at a time

Your goal is signal, not noise. Only surface things that are genuinely relevant
to the project's goals. Be concise and specific in reports.
```

- [ ] **Step 5.2: Commit**

```bash
git add images/apps/newsfromthefront/files/whoami/index.md
git commit -m "feat(newsfromthefront): add whoami identity file"
```

---

### Task 6: Write researcher prompt

**Files:**
- Create: `images/apps/newsfromthefront/files/newsfromthefront/researcher.md`

- [ ] **Step 6.1: Write the file**

````markdown
# newsfromthefront Researcher

You run the daily research phase. Your job is to gather raw competitive
intelligence and save it for the analyst.

## Steps

### 1. Read the project brief

```python
brief = dir.read("newsfromthefront/brief.md")
print(brief.content)
```

The brief contains: GitHub URL, project goals, known competitors, context notes
added by the owner over time.

### 2. Fetch the GitHub repo summary

Use the GitHub URL from the brief to get the project's README:

```python
import json, urllib.request, urllib.parse

token = secrets.get("cogent/github_token").value
# Convert https://github.com/owner/repo → owner/repo
repo_path = github_url.replace("https://github.com/", "").rstrip("/")
req = urllib.request.Request(
    f"https://api.github.com/repos/{repo_path}/readme",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.raw+json"},
)
with urllib.request.urlopen(req) as r:
    readme = r.read().decode()[:3000]  # first 3000 chars
```

### 3. Derive search queries from the brief

Based on the project description, goals, and known competitors, generate 6–10
search queries. Think about:
- What problem does this project solve? Who else solves it?
- What recent product launches, funding rounds, or blog posts are relevant?
- What are practitioners saying on Twitter about this problem space?
- What new GitHub repos have appeared in this area?

### 4. Run searches across all three backends

```python
import datetime
today = datetime.date.today().isoformat()

findings = []

# Perplexity — general web, news, blog posts
for query in perplexity_queries:
    result = web_search.search(query, recency="day")
    findings.append({"source": "perplexity", "query": query, "result": result.dict()})

# GitHub — new repos and activity in this space
for query in github_queries:
    result = web_search.search_github(query, type="repositories")
    findings.append({"source": "github", "query": query, "result": result.dict()})

# Twitter — practitioner discourse and competitor announcements
for query in twitter_queries:
    result = web_search.search_twitter(query, recency="day")
    findings.append({"source": "twitter", "query": query, "result": result.dict()})
```

### 5. Write findings file

```python
import json, uuid

run_id = str(uuid.uuid4())
findings_key = f"newsfromthefront/findings/{today}.md"

content = f"# Findings — {today}\n\nrun_id: {run_id}\n\n"
for f in findings:
    content += f"## {f['source'].upper()}: {f['query']}\n\n"
    content += json.dumps(f['result'], indent=2) + "\n\n"

dir.write(findings_key, content)
print(f"Wrote findings to {findings_key}")
```

### 6. Signal the analyst

```python
channels.send("newsfromthefront:findings-ready", {
    "run_id": run_id,
    "findings_key": findings_key,
    "date": today,
    "is_test": False,
    "is_backfill": False,
})
print("Signalled analyst via newsfromthefront:findings-ready")
```

## Notes

- If the GitHub API is unavailable, skip step 2 and proceed with the cached brief description.
- The brief evolves over time — always re-read it fresh; don't rely on prior context.
- Aim for broad coverage: 3–4 Perplexity queries, 2–3 GitHub queries, 2–3 Twitter queries.
````

- [ ] **Step 6.2: Commit**

```bash
git add images/apps/newsfromthefront/files/newsfromthefront/researcher.md
git commit -m "feat(newsfromthefront): add researcher prompt"
```

---

### Task 7: Write analyst prompt

**Files:**
- Create: `images/apps/newsfromthefront/files/newsfromthefront/analyst.md`

- [ ] **Step 7.1: Write the file**

````markdown
# newsfromthefront Analyst

You handle two cases depending on which channel triggered you. Inspect the
channel message payload to determine which:

- If payload has `findings_key` → **findings flow** (new research to analyze)
- If payload has `thread_id` → **feedback flow** (user replied to a report)

---

## Findings Flow

### 1. Read inputs

```python
import json

# The triggering message payload is in the channel message
findings_text = dir.read(payload["findings_key"]).content
kb_file = dir.read("newsfromthefront/knowledge-base.json")
kb = json.loads(kb_file.content) if kb_file else {"findings": [], "competitors": [], "last_run": ""}
```

### 2. Identify new findings

Compare the raw findings against `kb["findings"]`. A finding is NEW if its URL
has not been seen before (check `kb["findings"][*]["url"]`). Classify each new
finding:

- `competitor` — a product/project solving the same problem
- `product_update` — a new feature/release from a known competitor
- `funding` — investment or acquisition news
- `launch` — new product launch in the space
- `other` — relevant but doesn't fit above

### 3. Write the delta report

```python
date = payload["date"]
report_key = f"newsfromthefront/reports/{date}.md"

report = f"# Newsfromthefront — {date}\n\n"
if not new_findings:
    report += "_No new developments today._\n"
else:
    for f in new_findings:
        report += f"## [{f['type'].upper()}] {f['title']}\n"
        report += f"{f['summary']}\n"
        report += f"[Source]({f['url']})\n\n"
        report += f"**Why it matters:** {f['relevance']}\n\n"

dir.write(report_key, report)
```

### 4. Post to Discord (production runs only)

Skip this step if `payload["is_test"]` is True or `payload["is_backfill"]` is True.

```python
state_file = dir.read("newsfromthefront/state.json")
state = json.loads(state_file.content) if state_file else {"threads": {}}

discord_channel_id = secrets.get("cogent/discord_channel_id").value
# Use "TEST" prefix for test runs so they're easy to distinguish in Discord
thread_title = (
    f"Newsfromthefront TEST — {date}" if payload["is_test"]
    else f"Newsfromthefront — {date}"
)
thread = discord.create_thread(discord_channel_id, thread_title)
discord.send(thread.id, report)

state["threads"][thread.id] = {"date": date, "report_key": report_key}
dir.write("newsfromthefront/state.json", json.dumps(state, indent=2))
```

### 5. Update knowledge base (skip if is_test)

```python
if not payload["is_test"]:
    for f in new_findings:
        kb["findings"].append(f)
    kb["last_run"] = date
    dir.write("newsfromthefront/knowledge-base.json", json.dumps(kb, indent=2))
```

---

## Feedback Flow

The user replied to a report thread and @mentioned the bot.

### 1. Read and incorporate feedback

```python
feedback = payload["content"]
author = payload["author"]

brief = dir.read("newsfromthefront/brief.md").content
```

Read the feedback carefully. Update the brief to incorporate:
- New goals or constraints the user mentioned
- Competitors to add or remove from focus
- Changes to search focus or priorities
- Any context that will improve future research runs

### 2. Save updated brief

```python
dir.write("newsfromthefront/brief.md", updated_brief)
```

### 3. Confirm in Discord

```python
discord.send(payload["thread_id"], "Brief updated.")
```

---

## Notes

- Keep Discord reports concise: a header, one paragraph per finding, source link.
- If Discord posting fails, log the error but don't fail — the report is already saved to the file store.
- `secrets.get("cogent/discord_channel_id")` holds the Discord channel ID to post reports in.
````

- [ ] **Step 7.2: Commit**

```bash
git add images/apps/newsfromthefront/files/newsfromthefront/analyst.md
git commit -m "feat(newsfromthefront): add analyst prompt"
```

---

### Task 8: Write test and backfill prompts

**Files:**
- Create: `images/apps/newsfromthefront/files/newsfromthefront/test.md`
- Create: `images/apps/newsfromthefront/files/newsfromthefront/backfill.md`

- [ ] **Step 8.1: Write `test.md`**

````markdown
# newsfromthefront Test Runner

You run an end-to-end competitive analysis loop for testing. This never touches
the production knowledge base — it is safe to run at any time.

### 1. Check mode

```python
if payload["mode"] != "test":
    print("Not a test request — exiting.")
    exit()
```

### 2. Run researcher logic inline

Follow the same steps as the researcher prompt (`newsfromthefront/researcher.md`),
but set `is_test = True` in the findings-ready message:

```python
channels.send("newsfromthefront:findings-ready", {
    "run_id": run_id,
    "findings_key": findings_key,
    "date": today,
    "is_test": True,
    "is_backfill": False,
})
```

The analyst will handle the rest, skip KB updates, and post to a labeled test thread.

## Notes

- The test is triggered by `@cogent test` in any Discord channel.
- `discord-handle-message` detects the "test" command and sends to `newsfromthefront:run-requested`
  with `{"mode": "test", "after_date": "", "before_date": ""}`.
- Results appear in a thread titled "Newsfromthefront TEST — `<date>`".
````

- [ ] **Step 8.2: Write `backfill.md`**

````markdown
# newsfromthefront Backfill

You fill in the knowledge base with historical competitive intelligence, one
interval at a time. Each invocation processes a single interval then
re-triggers itself for the next one.

### 1. Check mode

```python
if payload["mode"] != "backfill":
    print("Not a backfill request — exiting.")
    exit()
```

### 2. Initialize or resume backfill state

```python
import json, datetime

state_file = dir.read("newsfromthefront/backfill-state.json")
if state_file and payload["after_date"] == "":
    # Resuming an in-progress backfill
    state = json.loads(state_file.content)
else:
    # Starting a new backfill
    after = payload["after_date"]
    before = payload["before_date"]
    after_dt = datetime.date.fromisoformat(after)
    before_dt = datetime.date.fromisoformat(before)
    # Week-by-week for ranges > 30 days, day-by-day otherwise
    delta_days = (before_dt - after_dt).days
    granularity = 7 if delta_days > 30 else 1
    state = {
        "after_date": after,
        "before_date": before,
        "current_date": after,
        "granularity_days": granularity,
        "intervals_done": 0,
        "findings_count": 0,
    }
    dir.write("newsfromthefront/backfill-state.json", json.dumps(state, indent=2))
```

### 3. Process the next interval

```python
import uuid

current = datetime.date.fromisoformat(state["current_date"])
interval_end = min(
    current + datetime.timedelta(days=state["granularity_days"]),
    datetime.date.fromisoformat(state["before_date"]),
)
interval_str = current.isoformat()

# Run searches for this interval using date range params
findings = []
brief = dir.read("newsfromthefront/brief.md").content

# Run Perplexity, GitHub, Twitter searches with after_date/before_date
# (follow the same query generation logic as researcher.md)
# ...

run_id = str(uuid.uuid4())
findings_key = f"newsfromthefront/findings/{interval_str}.md"
dir.write(findings_key, findings_content)

# Signal analyst with is_backfill=True (skips Discord posting)
channels.send("newsfromthefront:findings-ready", {
    "run_id": run_id,
    "findings_key": findings_key,
    "date": interval_str,
    "is_test": False,
    "is_backfill": True,
})
```

### 4. Advance state

After running the analyst-style deduplication (compare findings against `knowledge-base.json`
by URL, keep only items whose URL has not been seen before), you will have a `new_findings` list.
Update the knowledge base and advance the state:

```python
# Load KB and deduplicate
kb_file = dir.read("newsfromthefront/knowledge-base.json")
kb = json.loads(kb_file.content) if kb_file else {"findings": [], "competitors": [], "last_run": ""}
seen_urls = {f["url"] for f in kb["findings"]}
new_findings = [f for f in all_findings if f.get("url") not in seen_urls]

for f in new_findings:
    kb["findings"].append(f)
kb["last_run"] = interval_str
dir.write("newsfromthefront/knowledge-base.json", json.dumps(kb, indent=2))

state["current_date"] = interval_end.isoformat()
state["intervals_done"] += 1
state["findings_count"] += len(new_findings)
dir.write("newsfromthefront/backfill-state.json", json.dumps(state, indent=2))
```

### 5. Self-trigger or complete

```python
before_dt = datetime.date.fromisoformat(state["before_date"])
if interval_end < before_dt:
    # More intervals remain — re-trigger self
    channels.send("newsfromthefront:run-requested", {
        "mode": "backfill",
        "after_date": "",   # empty = resume from state file
        "before_date": "",
    })
    print(f"Backfill continuing — {state['intervals_done']} intervals done, next: {interval_end}")
else:
    # All done
    discord_channel_id = secrets.get("cogent/discord_channel_id").value
    discord.send(discord_channel_id,
        f"Backfill complete: {state['after_date']} → {state['before_date']}. "
        f"Knowledge base initialized with {state['findings_count']} findings."
    )
    dir.delete("newsfromthefront/backfill-state.json")
    print("Backfill complete.")
```

## Notes

- Backfill is triggered by `@cogent backfill 2025-01-01 2025-03-01` in Discord.
- `discord-handle-message` parses the dates and sends to `newsfromthefront:run-requested`.
- A crash mid-backfill is safe — re-running `@cogent backfill` with new dates restarts from scratch,
  or omit dates to resume (not yet implemented; for now, re-run with original dates and the KB
  deduplication will skip already-seen findings).
````

- [ ] **Step 8.3: Commit**

```bash
git add images/apps/newsfromthefront/files/newsfromthefront/
git commit -m "feat(newsfromthefront): add test and backfill prompts"
```

---

## Chunk 4: Discord Routing + Setup

### Task 9: Update `discord-handle-message` in cogent-v1

`discord-handle-message` currently uses inline `content=`. Convert it to a `code_key` pointing to a file, and add logic to route `newsfromthefront` thread replies and commands.

**Files:**
- Create: `images/cogent-v1/files/cogos/lib/discord-handle-message.md`
- Modify: `images/cogent-v1/init/processes.py`

- [ ] **Step 9.1: Create the prompt file**

```markdown
# discord-handle-message

You received a Discord message. The channel message payload tells you who sent
it and what they said. Check the payload fields to decide how to respond.

## Routing logic

### 1. Check for newsfromthefront thread replies

```python
import json

state_file = dir.read("newsfromthefront/state.json")
state = json.loads(state_file.content) if state_file else {"threads": {}}
known_threads = state.get("threads", {})

# payload fields from io:discord:mention include channel_id (thread ID if in a thread)
thread_id = payload.get("channel_id", "")

if thread_id and thread_id in known_threads:
    # This is a reply to a newsfromthefront report thread — route as feedback
    channels.send("newsfromthefront:discord-feedback", {
        "thread_id": thread_id,
        "content": payload["content"],
        "author": payload["author"],
    })
    exit()
```

### 2. Check for newsfromthefront commands

```python
content = payload.get("content", "").strip().lower()

if content == "test" or content.startswith("test "):
    channels.send("newsfromthefront:run-requested", {
        "mode": "test",
        "after_date": "",
        "before_date": "",
    })
    discord.send(payload["channel_id"], "Starting test run — results will appear in a new thread.")
    exit()

if content.startswith("backfill "):
    parts = content.split()
    if len(parts) == 3:
        after_date, before_date = parts[1], parts[2]
        channels.send("newsfromthefront:run-requested", {
            "mode": "backfill",
            "after_date": after_date,
            "before_date": before_date,
        })
        discord.send(payload["channel_id"], f"Starting backfill {after_date} → {before_date}.")
        exit()
```

### 3. Normal chat response

For all other messages, respond helpfully:

- For DMs (`payload["dm"] == true`): use `discord.dm(user_id=payload["author_id"], content=your_reply)`
- For mentions: use `discord.send(channel=payload["channel_id"], content=your_reply)`

Be helpful, concise, and friendly. If you don't know something, say so.
```

- [ ] **Step 9.2: Update `images/cogent-v1/init/processes.py`**

Replace the `discord-handle-message` `add_process` call. Change `content="""..."""` to `code_key="cogos/lib/discord-handle-message"` and remove the inline content string:

```python
add_process(
    "discord-handle-message",
    mode="daemon",
    code_key="cogos/lib/discord-handle-message",
    runner="lambda",
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    priority=10.0,
    capabilities=["discord", "channels", "dir"],
    handlers=["io:discord:dm", "io:discord:mention"],
)
```

- [ ] **Step 9.3: Verify cogent-v1 image still loads**

```bash
python - <<'EOF'
from pathlib import Path
from cogos.image.spec import load_image
spec = load_image(Path("images/cogent-v1"))
proc_names = [p["name"] for p in spec.processes]
assert "discord-handle-message" in proc_names
dh = next(p for p in spec.processes if p["name"] == "discord-handle-message")
assert dh["code_key"] == "cogos/lib/discord-handle-message"
assert dh["content"] == ""
print("cogent-v1 image loads correctly")
print(f"discord-handle-message code_key: {dh['code_key']}")
EOF
```

- [ ] **Step 9.4: Commit**

```bash
git add images/cogent-v1/files/cogos/lib/discord-handle-message.md
git add images/cogent-v1/init/processes.py
git commit -m "feat(cogent-v1): convert discord-handle-message to code_key, add newsfromthefront routing"
```

---

### Task 10: Add required secret — `cogent/discord_channel_id`

The analyst needs to know which Discord channel to post reports in.

- [ ] **Step 10.1: Store the secret**

```bash
# Replace CHANNEL_ID with the actual Discord channel ID for reports
aws secretsmanager create-secret \
  --name "cogent/discord_channel_id" \
  --secret-string '{"value": "CHANNEL_ID"}'
```

Verify the three new secrets exist (`perplexity_api_key`, `twitter_bearer_token` should already be set before boot):
```bash
aws secretsmanager list-secrets --query 'SecretList[?starts_with(Name, `cogent/`)].Name' --output table
```

---

### Task 11: Boot and smoke test

- [ ] **Step 11.1: Boot the newsfromthefront image**

```bash
cogent dr.alpha cogos image boot newsfromthefront --image-dir images/apps/newsfromthefront
```

- [ ] **Step 11.2: Verify all four processes are WAITING**

```bash
cogent dr.alpha cogos process list | grep newsfromthefront
```
Expected: four rows, all `WAITING`.

- [ ] **Step 11.3: Write an initial `brief.md`**

```bash
cogent dr.alpha cogos file create newsfromthefront/brief.md --content "$(cat <<'EOF'
# Project Brief

## GitHub Repository
https://github.com/<owner>/<repo>

## What This Project Does
<one paragraph description>

## Goals
- <goal 1>
- <goal 2>

## Known Competitors
- <competitor 1>
- <competitor 2>

## Search Focus
<topics, keywords, or problem areas to track>

## Context Notes
(Updated automatically via Discord thread replies)
EOF
)"
```

Replace placeholders with the actual project details.

- [ ] **Step 11.4: Trigger a test run from Discord**

In the configured Discord server, mention the bot:
```
@cogent test
```

Expected: bot replies "Starting test run — results will appear in a new thread." A new thread titled "Newsfromthefront TEST — `<date>`" appears within ~2 minutes.

- [ ] **Step 11.5: Verify the run in the CLI**

```bash
cogent dr.alpha cogos run list | grep newsfromthefront | head -10
```
Expected: runs for `newsfromthefront-test`, `newsfromthefront-researcher`, and `newsfromthefront-analyst` all with status `SUCCESS`.

- [ ] **Step 11.6: Reboot cogent-v1 to pick up discord-handle-message changes**

```bash
cogent dr.alpha cogos image boot cogent-v1
```

- [ ] **Step 11.7: Commit final state**

```bash
git add .
git commit -m "feat(newsfromthefront): complete implementation — capability, image, prompts, routing"
```

---

## Tuning Guide (post-boot)

**Tune search queries only** (no Perplexity credits spent):
```bash
# Manually trigger researcher and read raw findings
cogent dr.alpha cogos channel send newsfromthefront:tick '{}'
# Wait ~1 minute, then:
cogent dr.alpha cogos file get newsfromthefront/findings/<today>.md
```

**Tune report formatting only** (analyst only, no searches):
```bash
# Drop a findings file manually and trigger analyst with is_test=true
cogent dr.alpha cogos channel send newsfromthefront:findings-ready \
  '{"run_id":"test-001","findings_key":"newsfromthefront/findings/<date>.md","date":"<date>","is_test":true,"is_backfill":false}'
```

**Seed the knowledge base** (historical context before daily runs start):
```
@cogent backfill 2025-01-01 2026-03-01
```
