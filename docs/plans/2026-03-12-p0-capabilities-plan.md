# P0 Capabilities Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement four new CogOS capabilities (WebSearch, WebFetch, Asana, GitHub) for the recruiter MVP.

**Architecture:** Each capability extends `Capability` base class (in `src/cogos/capabilities/base.py`), implements `_narrow()`/`_check()` for scoping, and exposes public methods returning Pydantic models. Capabilities fetch their own API keys from AWS SSM/Secrets Manager via a shared helper. Each is registered in `BUILTIN_CAPABILITIES` in `src/cogos/capabilities/__init__.py`.

**Tech Stack:** `tavily-python`, `trafilatura`, `asana`, `PyGithub`, `httpx`, `boto3`

**Design doc:** `docs/plans/2026-03-12-p0-capabilities-design.md`

---

### Task 1: Add pip dependencies

**Files:**
- Modify: `pyproject.toml:6-23` (dependencies list)

**Step 1: Add dependencies**

Add to `dependencies` list in `pyproject.toml`:

```
"tavily-python>=0.5",
"trafilatura>=2.0",
"asana>=5.0",
"PyGithub>=2.0",
"httpx>=0.27",
```

Note: `httpx` is already in dev deps but needs to be in main deps for WebFetch.

**Step 2: Install**

Run: `uv sync`
Expected: All packages install successfully.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add tavily, trafilatura, asana, PyGithub, httpx for P0 capabilities"
```

---

### Task 2: Shared secrets helper

**Files:**
- Create: `src/cogos/capabilities/_secrets_helper.py`
- Test: `tests/cogos/capabilities/test_secrets_helper.py`

**Step 1: Write the failing test**

```python
"""Tests for _secrets_helper.fetch_secret."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogos.capabilities._secrets_helper import fetch_secret


class TestFetchSecretSSM:
    def test_returns_value_from_ssm(self):
        with patch("boto3.client") as mock_client:
            mock_ssm = MagicMock()
            mock_ssm.get_parameter.return_value = {
                "Parameter": {"Value": "my-secret-value"}
            }
            mock_client.return_value = mock_ssm
            result = fetch_secret("cogos/api-key")
            assert result == "my-secret-value"
            mock_client.assert_called_with("ssm")

    def test_falls_back_to_secrets_manager(self):
        with patch("boto3.client") as mock_client:
            mock_ssm = MagicMock()
            mock_ssm.get_parameter.side_effect = Exception("not found")
            mock_sm = MagicMock()
            mock_sm.get_secret_value.return_value = {"SecretString": "sm-value"}

            def pick_client(service):
                return mock_ssm if service == "ssm" else mock_sm

            mock_client.side_effect = pick_client
            result = fetch_secret("cogos/api-key")
            assert result == "sm-value"

    def test_raises_on_both_fail(self):
        with patch("boto3.client") as mock_client:
            mock_ssm = MagicMock()
            mock_ssm.get_parameter.side_effect = Exception("ssm fail")
            mock_sm = MagicMock()
            mock_sm.get_secret_value.side_effect = Exception("sm fail")

            def pick_client(service):
                return mock_ssm if service == "ssm" else mock_sm

            mock_client.side_effect = pick_client
            with pytest.raises(RuntimeError, match="Could not fetch secret"):
                fetch_secret("cogos/api-key")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_secrets_helper.py -v`
Expected: FAIL — ImportError (module doesn't exist yet)

**Step 3: Write implementation**

```python
"""Shared secret fetching — SSM Parameter Store with Secrets Manager fallback."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def fetch_secret(key: str) -> str:
    """Fetch a secret value from AWS SSM Parameter Store or Secrets Manager.

    Tries SSM first, then Secrets Manager. Returns the string value.
    Raises RuntimeError if both fail.
    """
    import boto3

    # Try SSM Parameter Store
    try:
        client = boto3.client("ssm")
        resp = client.get_parameter(Name=key, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        pass

    # Try Secrets Manager
    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=key)
        value = resp.get("SecretString")
        if value is None:
            raise RuntimeError(f"Secret '{key}' is binary, not string")
        # If it's JSON, return as-is (string form) — caller can parse if needed
        return value
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not fetch secret '{key}': {exc}") from exc
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_secrets_helper.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/cogos/capabilities/_secrets_helper.py tests/cogos/capabilities/test_secrets_helper.py
git commit -m "feat(capabilities): add shared secrets helper for API key fetching"
```

---

### Task 3: WebSearchCapability

**Files:**
- Create: `src/cogos/capabilities/web_search.py`
- Test: `tests/cogos/capabilities/test_web_search.py`
- Modify: `src/cogos/capabilities/__init__.py` (add to BUILTIN_CAPABILITIES)

**Step 1: Write the failing tests**

```python
"""Tests for WebSearchCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.web_search import (
    SearchResult,
    WebSearchCapability,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScoping:
    def test_unscoped_allows_any_search(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        cap._check("search")  # should not raise

    def test_scoped_ops_denies_unpermitted(self, repo, pid):
        cap = WebSearchCapability(repo, pid).scope(ops=["search"])
        with pytest.raises(PermissionError):
            cap._check("other_op")

    def test_narrow_intersects_ops(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        s1 = cap.scope(ops=["search"])
        s2 = s1.scope(ops=["search"])
        assert s2._scope["ops"] == ["search"]

    def test_narrow_intersects_domains(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        s1 = cap.scope(domains=["github.com", "linkedin.com"])
        s2 = s1.scope(domains=["github.com", "twitter.com"])
        assert s2._scope["domains"] == ["github.com"]

    def test_narrow_budget_takes_min(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        s1 = cap.scope(query_budget=100)
        s2 = s1.scope(query_budget=50)
        assert s2._scope["query_budget"] == 50


class TestSearch:
    @patch("cogos.capabilities.web_search.fetch_secret", return_value="test-api-key")
    def test_search_returns_results(self, mock_secret, repo, pid):
        cap = WebSearchCapability(repo, pid)
        mock_response = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Snippet 1",
                    "score": 0.95,
                },
            ]
        }
        with patch("cogos.capabilities.web_search.TavilyClient") as MockTavily:
            mock_client = MagicMock()
            mock_client.search.return_value = mock_response
            MockTavily.return_value = mock_client

            results = cap.search("test query", limit=5)
            assert len(results) == 1
            assert isinstance(results[0], SearchResult)
            assert results[0].title == "Result 1"
            mock_client.search.assert_called_once_with(
                query="test query",
                max_results=5,
                include_domains=None,
            )

    @patch("cogos.capabilities.web_search.fetch_secret", return_value="test-api-key")
    def test_search_with_domain_scope(self, mock_secret, repo, pid):
        cap = WebSearchCapability(repo, pid).scope(domains=["github.com"])
        with patch("cogos.capabilities.web_search.TavilyClient") as MockTavily:
            mock_client = MagicMock()
            mock_client.search.return_value = {"results": []}
            MockTavily.return_value = mock_client

            cap.search("test query")
            mock_client.search.assert_called_once_with(
                query="test query",
                max_results=5,
                include_domains=["github.com"],
            )

    @patch("cogos.capabilities.web_search.fetch_secret", side_effect=RuntimeError("no key"))
    def test_search_returns_error_on_missing_key(self, mock_secret, repo, pid):
        cap = WebSearchCapability(repo, pid)
        result = cap.search("test")
        assert hasattr(result, "error")
        assert "no key" in result.error
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_web_search.py -v`
Expected: FAIL — ImportError

**Step 3: Write implementation**

```python
"""Web search capability — search the web via Tavily API."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None  # type: ignore[assignment,misc]


# ── IO Models ────────────────────────────────────────────────


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: float


class SearchError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────

SECRET_KEY = "cogos/tavily-api-key"


class WebSearchCapability(Capability):
    """Web search via Tavily API.

    Usage:
        web_search.search("AI engineer Bay Area")
    """

    ALL_OPS = {"search"}

    def __init__(self, repo, process_id) -> None:
        super().__init__(repo, process_id)
        self._api_key: str | None = None

    def _get_api_key(self) -> str:
        if self._api_key is None:
            self._api_key = fetch_secret(SECRET_KEY)
        return self._api_key

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        # ops — set intersection
        old_ops = existing.get("ops")
        new_ops = requested.get("ops")
        if old_ops is not None and new_ops is not None:
            result["ops"] = [o for o in old_ops if o in new_ops]
        elif old_ops is not None:
            result["ops"] = old_ops
        elif new_ops is not None:
            result["ops"] = new_ops
        # domains — list intersection
        old_dom = existing.get("domains")
        new_dom = requested.get("domains")
        if old_dom is not None and new_dom is not None:
            result["domains"] = [d for d in old_dom if d in new_dom]
        elif old_dom is not None:
            result["domains"] = old_dom
        elif new_dom is not None:
            result["domains"] = new_dom
        # query_budget — min
        old_b = existing.get("query_budget")
        new_b = requested.get("query_budget")
        if old_b is not None and new_b is not None:
            result["query_budget"] = min(old_b, new_b)
        elif old_b is not None:
            result["query_budget"] = old_b
        elif new_b is not None:
            result["query_budget"] = new_b
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")

    def search(self, query: str, limit: int = 5) -> list[SearchResult] | SearchError:
        """Search the web. Returns a list of results or an error."""
        self._check("search")
        try:
            api_key = self._get_api_key()
            client = TavilyClient(api_key=api_key)
            domains = self._scope.get("domains") if self._scope else None
            response = client.search(
                query=query,
                max_results=limit,
                include_domains=domains,
            )
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    score=r.get("score", 0.0),
                )
                for r in response.get("results", [])
            ]
        except Exception as exc:
            return SearchError(error=str(exc))

    def __repr__(self) -> str:
        return "<WebSearchCapability search()>"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_web_search.py -v`
Expected: All passed

**Step 5: Register in BUILTIN_CAPABILITIES**

Add to the end of `BUILTIN_CAPABILITIES` list in `src/cogos/capabilities/__init__.py`:

```python
{
    "name": "web_search",
    "description": "Search the web via Tavily API.",
    "handler": "cogos.capabilities.web_search.WebSearchCapability",
    "instructions": (
        "Use web_search to search the web.\n"
        "- web_search.search(query, limit=5) — search and return results\n"
        "Returns a list of SearchResult(title, url, snippet, score) or SearchError.\n"
        "API key is managed internally. Never log or expose it."
    ),
    "schema": {
        "scope": {
            "properties": {
                "domains": {"type": "array", "items": {"type": "string"}, "description": "Domain allowlist"},
                "query_budget": {"type": "integer", "description": "Max queries allowed"},
                "ops": {"type": "array", "items": {"type": "string", "enum": ["search"]}},
            },
        },
        "search": {
            "input": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 5, "description": "Max results"},
                },
                "required": ["query"],
            },
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"}, "url": {"type": "string"},
                        "snippet": {"type": "string"}, "score": {"type": "number"},
                    },
                },
            },
        },
    },
},
```

**Step 6: Run all tests**

Run: `pytest tests/cogos/capabilities/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/cogos/capabilities/web_search.py src/cogos/capabilities/__init__.py tests/cogos/capabilities/test_web_search.py
git commit -m "feat(capabilities): add WebSearchCapability with Tavily API"
```

---

### Task 4: WebFetchCapability

**Files:**
- Create: `src/cogos/capabilities/web_fetch.py`
- Test: `tests/cogos/capabilities/test_web_fetch.py`
- Modify: `src/cogos/capabilities/__init__.py`

**Step 1: Write the failing tests**

```python
"""Tests for WebFetchCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.web_fetch import (
    FetchError,
    PageContent,
    TextContent,
    WebFetchCapability,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScoping:
    def test_unscoped_allows_any_domain(self, repo, pid):
        cap = WebFetchCapability(repo, pid)
        cap._check("fetch", url="https://anything.com/page")

    def test_scoped_domains_allows_matching(self, repo, pid):
        cap = WebFetchCapability(repo, pid).scope(domains=["github.com"])
        cap._check("fetch", url="https://github.com/user/repo")

    def test_scoped_domains_denies_non_matching(self, repo, pid):
        cap = WebFetchCapability(repo, pid).scope(domains=["github.com"])
        with pytest.raises(PermissionError):
            cap._check("fetch", url="https://evil.com/phish")

    def test_narrow_intersects_domains(self, repo, pid):
        cap = WebFetchCapability(repo, pid)
        s1 = cap.scope(domains=["github.com", "linkedin.com"])
        s2 = s1.scope(domains=["github.com", "twitter.com"])
        assert s2._scope["domains"] == ["github.com"]


class TestFetch:
    @patch("cogos.capabilities.web_fetch.httpx")
    def test_fetch_returns_page_content(self, mock_httpx, repo, pid):
        cap = WebFetchCapability(repo, pid)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response

        result = cap.fetch("https://example.com")
        assert isinstance(result, PageContent)
        assert result.status_code == 200
        assert "Hello" in result.html

    @patch("cogos.capabilities.web_fetch.httpx")
    def test_fetch_error_on_failure(self, mock_httpx, repo, pid):
        cap = WebFetchCapability(repo, pid)
        mock_httpx.get.side_effect = Exception("connection refused")

        result = cap.fetch("https://down.example.com")
        assert isinstance(result, FetchError)
        assert "connection refused" in result.error


class TestExtractText:
    @patch("cogos.capabilities.web_fetch.trafilatura")
    @patch("cogos.capabilities.web_fetch.httpx")
    def test_extract_text_returns_content(self, mock_httpx, mock_traf, repo, pid):
        cap = WebFetchCapability(repo, pid)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body><p>Article text here</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response
        mock_traf.extract.return_value = "Article text here"
        mock_metadata = MagicMock()
        mock_metadata.title = "Page Title"
        mock_traf.extract_metadata.return_value = mock_metadata

        result = cap.extract_text("https://example.com/article")
        assert isinstance(result, TextContent)
        assert result.text == "Article text here"
        assert result.title == "Page Title"

    @patch("cogos.capabilities.web_fetch.trafilatura")
    @patch("cogos.capabilities.web_fetch.httpx")
    def test_extract_text_empty_extraction(self, mock_httpx, mock_traf, repo, pid):
        cap = WebFetchCapability(repo, pid)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html></html>"
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response
        mock_traf.extract.return_value = None

        result = cap.extract_text("https://example.com/empty")
        assert isinstance(result, FetchError)
        assert "extract" in result.error.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_web_fetch.py -v`
Expected: FAIL — ImportError

**Step 3: Write implementation**

```python
"""Web fetch capability — fetch and extract content from URLs."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]


# ── IO Models ────────────────────────────────────────────────


class PageContent(BaseModel):
    url: str
    html: str
    status_code: int


class TextContent(BaseModel):
    url: str
    text: str
    title: str = ""


class FetchError(BaseModel):
    url: str
    error: str


# ── Capability ───────────────────────────────────────────────

_TIMEOUT = 30.0
_MAX_SIZE = 5 * 1024 * 1024  # 5 MB


class WebFetchCapability(Capability):
    """Fetch and extract content from URLs.

    Usage:
        web_fetch.fetch("https://example.com")
        web_fetch.extract_text("https://blog.example.com/post")
    """

    ALL_OPS = {"fetch", "extract_text"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        # domains — list intersection
        old_dom = existing.get("domains")
        new_dom = requested.get("domains")
        if old_dom is not None and new_dom is not None:
            result["domains"] = [d for d in old_dom if d in new_dom]
        elif old_dom is not None:
            result["domains"] = old_dom
        elif new_dom is not None:
            result["domains"] = new_dom
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        domains = self._scope.get("domains")
        if domains is not None:
            url = str(context.get("url", ""))
            hostname = urlparse(url).hostname or ""
            if not any(hostname == d or hostname.endswith(f".{d}") for d in domains):
                raise PermissionError(
                    f"Domain '{hostname}' not in allowed list: {domains}"
                )

    def fetch(self, url: str) -> PageContent | FetchError:
        """Fetch raw HTML from a URL."""
        self._check("fetch", url=url)
        try:
            response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            return PageContent(url=url, html=response.text[:_MAX_SIZE], status_code=response.status_code)
        except Exception as exc:
            return FetchError(url=url, error=str(exc))

    def extract_text(self, url: str) -> TextContent | FetchError:
        """Fetch a URL and extract clean text content."""
        self._check("extract_text", url=url)
        try:
            response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
            response.raise_for_status()
            html = response.text
            text = trafilatura.extract(html)
            if text is None:
                return FetchError(url=url, error="Could not extract text content")
            metadata = trafilatura.extract_metadata(html)
            title = metadata.title if metadata and metadata.title else ""
            return TextContent(url=url, text=text, title=title)
        except Exception as exc:
            return FetchError(url=url, error=str(exc))

    def __repr__(self) -> str:
        return "<WebFetchCapability fetch() extract_text()>"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_web_fetch.py -v`
Expected: All passed

**Step 5: Register in BUILTIN_CAPABILITIES**

Add to `src/cogos/capabilities/__init__.py`:

```python
{
    "name": "web_fetch",
    "description": "Fetch and extract content from URLs.",
    "handler": "cogos.capabilities.web_fetch.WebFetchCapability",
    "instructions": (
        "Use web_fetch to fetch web pages and extract text.\n"
        "- web_fetch.fetch(url) — fetch raw HTML from a URL\n"
        "- web_fetch.extract_text(url) — fetch and extract clean text content\n"
        "Returns PageContent/TextContent or FetchError.\n"
        "Useful for reading GitHub profiles, blog posts, articles."
    ),
    "schema": {
        "scope": {
            "properties": {
                "domains": {"type": "array", "items": {"type": "string"}, "description": "Domain allowlist"},
            },
        },
        "fetch": {
            "input": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
            "output": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"}, "html": {"type": "string"},
                    "status_code": {"type": "integer"},
                },
            },
        },
        "extract_text": {
            "input": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to extract text from"},
                },
                "required": ["url"],
            },
            "output": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"}, "text": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        },
    },
},
```

**Step 6: Run all tests**

Run: `pytest tests/cogos/capabilities/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/cogos/capabilities/web_fetch.py src/cogos/capabilities/__init__.py tests/cogos/capabilities/test_web_fetch.py
git commit -m "feat(capabilities): add WebFetchCapability with httpx/trafilatura"
```

---

### Task 5: AsanaCapability

**Files:**
- Create: `src/cogos/capabilities/asana_cap.py`
- Test: `tests/cogos/capabilities/test_asana_cap.py`
- Modify: `src/cogos/capabilities/__init__.py`

Note: file is `asana_cap.py` to avoid shadowing the `asana` package.

**Step 1: Write the failing tests**

```python
"""Tests for AsanaCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.asana_cap import (
    AsanaCapability,
    AsanaError,
    CommentResult,
    TaskResult,
    TaskSummary,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScoping:
    def test_unscoped_allows_all(self, repo, pid):
        cap = AsanaCapability(repo, pid)
        cap._check("create_task")

    def test_scoped_ops_denies(self, repo, pid):
        cap = AsanaCapability(repo, pid).scope(ops=["list_tasks"])
        with pytest.raises(PermissionError):
            cap._check("create_task")

    def test_scoped_projects_denies(self, repo, pid):
        cap = AsanaCapability(repo, pid).scope(projects=["proj-1"])
        with pytest.raises(PermissionError):
            cap._check("create_task", project="proj-other")

    def test_narrow_intersects_ops(self, repo, pid):
        cap = AsanaCapability(repo, pid)
        s1 = cap.scope(ops=["create_task", "list_tasks", "update_task"])
        s2 = s1.scope(ops=["list_tasks", "add_comment"])
        assert s2._scope["ops"] == ["list_tasks"]

    def test_narrow_intersects_projects(self, repo, pid):
        cap = AsanaCapability(repo, pid)
        s1 = cap.scope(projects=["p1", "p2"])
        s2 = s1.scope(projects=["p2", "p3"])
        assert s2._scope["projects"] == ["p2"]


class TestCreateTask:
    @patch("cogos.capabilities.asana_cap.fetch_secret", return_value="test-pat")
    def test_create_task_success(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        mock_task = {
            "gid": "12345",
            "name": "Review candidate",
            "permalink_url": "https://app.asana.com/0/12345",
        }
        with patch("cogos.capabilities.asana_cap.asana") as mock_asana:
            mock_client = MagicMock()
            mock_client.tasks.create_task.return_value = mock_task
            mock_asana.Client.access_token.return_value = mock_client

            result = cap.create_task("proj-1", "Review candidate", notes="Good fit")
            assert isinstance(result, TaskResult)
            assert result.id == "12345"
            assert result.name == "Review candidate"

    @patch("cogos.capabilities.asana_cap.fetch_secret", side_effect=RuntimeError("no key"))
    def test_create_task_missing_key(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        result = cap.create_task("proj-1", "Test")
        assert isinstance(result, AsanaError)


class TestListTasks:
    @patch("cogos.capabilities.asana_cap.fetch_secret", return_value="test-pat")
    def test_list_tasks_success(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        mock_tasks = [
            {"gid": "1", "name": "Task 1", "completed": False, "assignee": {"name": "Alice"}, "due_on": "2026-03-15"},
            {"gid": "2", "name": "Task 2", "completed": True, "assignee": None, "due_on": None},
        ]
        with patch("cogos.capabilities.asana_cap.asana") as mock_asana:
            mock_client = MagicMock()
            mock_client.tasks.get_tasks.return_value = mock_tasks
            mock_asana.Client.access_token.return_value = mock_client

            results = cap.list_tasks("proj-1")
            assert len(results) == 2
            assert isinstance(results[0], TaskSummary)
            assert results[0].name == "Task 1"
            assert results[1].completed is True


class TestAddComment:
    @patch("cogos.capabilities.asana_cap.fetch_secret", return_value="test-pat")
    def test_add_comment_success(self, mock_secret, repo, pid):
        cap = AsanaCapability(repo, pid)
        mock_story = {"gid": "story-1"}
        with patch("cogos.capabilities.asana_cap.asana") as mock_asana:
            mock_client = MagicMock()
            mock_client.stories.create_story_for_task.return_value = mock_story
            mock_asana.Client.access_token.return_value = mock_client

            result = cap.add_comment("task-1", "Looks good")
            assert isinstance(result, CommentResult)
            assert result.id == "story-1"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_asana_cap.py -v`
Expected: FAIL — ImportError

**Step 3: Write implementation**

```python
"""Asana capability — create and manage Asana tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    import asana
except ImportError:
    asana = None  # type: ignore[assignment]


# ── IO Models ────────────────────────────────────────────────


class TaskResult(BaseModel):
    id: str
    name: str
    project: str = ""
    status: str = ""
    url: str = ""


class TaskSummary(BaseModel):
    id: str
    name: str
    assignee: str = ""
    due_on: str = ""
    completed: bool = False


class CommentResult(BaseModel):
    id: str
    task_id: str


class AsanaError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────

SECRET_KEY = "cogos/asana-pat"


class AsanaCapability(Capability):
    """Asana task management.

    Usage:
        asana.create_task("project-id", "Task name", notes="Details")
        asana.list_tasks("project-id")
    """

    ALL_OPS = {"create_task", "update_task", "list_tasks", "add_comment"}

    def __init__(self, repo, process_id) -> None:
        super().__init__(repo, process_id)
        self._api_key: str | None = None

    def _get_client(self):
        if self._api_key is None:
            self._api_key = fetch_secret(SECRET_KEY)
        return asana.Client.access_token(self._api_key)

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        for key in ("ops", "projects"):
            old = existing.get(key)
            new = requested.get(key)
            if old is not None and new is not None:
                result[key] = [v for v in old if v in new]
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")
        allowed_projects = self._scope.get("projects")
        if allowed_projects is not None:
            project = context.get("project", "")
            if project and str(project) not in allowed_projects:
                raise PermissionError(
                    f"Project '{project}' not in allowed list: {allowed_projects}"
                )

    def create_task(
        self,
        project: str,
        name: str,
        notes: str = "",
        assignee: str | None = None,
        due_on: str | None = None,
    ) -> TaskResult | AsanaError:
        """Create a task in an Asana project."""
        self._check("create_task", project=project)
        try:
            client = self._get_client()
            params: dict = {"projects": [project], "name": name}
            if notes:
                params["notes"] = notes
            if assignee:
                params["assignee"] = assignee
            if due_on:
                params["due_on"] = due_on
            task = client.tasks.create_task(params)
            return TaskResult(
                id=task["gid"],
                name=task.get("name", name),
                project=project,
                url=task.get("permalink_url", ""),
            )
        except Exception as exc:
            return AsanaError(error=str(exc))

    def update_task(self, task_id: str, **fields) -> TaskResult | AsanaError:
        """Update fields on an existing task."""
        self._check("update_task")
        try:
            client = self._get_client()
            task = client.tasks.update_task(task_id, fields)
            return TaskResult(
                id=task["gid"],
                name=task.get("name", ""),
                url=task.get("permalink_url", ""),
            )
        except Exception as exc:
            return AsanaError(error=str(exc))

    def list_tasks(self, project: str, limit: int = 50) -> list[TaskSummary] | AsanaError:
        """List tasks in a project."""
        self._check("list_tasks", project=project)
        try:
            client = self._get_client()
            tasks = client.tasks.get_tasks(
                {"project": project, "limit": limit, "opt_fields": "name,completed,assignee.name,due_on"}
            )
            return [
                TaskSummary(
                    id=t["gid"],
                    name=t.get("name", ""),
                    assignee=t.get("assignee", {}).get("name", "") if t.get("assignee") else "",
                    due_on=t.get("due_on") or "",
                    completed=t.get("completed", False),
                )
                for t in tasks
            ]
        except Exception as exc:
            return AsanaError(error=str(exc))

    def add_comment(self, task_id: str, text: str) -> CommentResult | AsanaError:
        """Add a comment to a task."""
        self._check("add_comment")
        try:
            client = self._get_client()
            story = client.stories.create_story_for_task(task_id, {"text": text})
            return CommentResult(id=story["gid"], task_id=task_id)
        except Exception as exc:
            return AsanaError(error=str(exc))

    def __repr__(self) -> str:
        return "<AsanaCapability create_task() update_task() list_tasks() add_comment()>"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_asana_cap.py -v`
Expected: All passed

**Step 5: Register in BUILTIN_CAPABILITIES**

Add to `src/cogos/capabilities/__init__.py`:

```python
{
    "name": "asana",
    "description": "Create and manage Asana tasks.",
    "handler": "cogos.capabilities.asana_cap.AsanaCapability",
    "instructions": (
        "Use asana to manage tasks in Asana.\n"
        "- asana.create_task(project, name, notes?, assignee?, due_on?) — create a task\n"
        "- asana.update_task(task_id, **fields) — update a task\n"
        "- asana.list_tasks(project, limit=50) — list tasks in a project\n"
        "- asana.add_comment(task_id, text) — add a comment to a task\n"
        "API key is managed internally. Uses Asana PAT for authentication."
    ),
    "schema": {
        "scope": {
            "properties": {
                "projects": {"type": "array", "items": {"type": "string"}, "description": "Allowed project GIDs"},
                "ops": {"type": "array", "items": {"type": "string", "enum": ["create_task", "update_task", "list_tasks", "add_comment"]}},
            },
        },
        "create_task": {
            "input": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"}, "name": {"type": "string"},
                    "notes": {"type": "string", "default": ""},
                    "assignee": {"type": "string"}, "due_on": {"type": "string"},
                },
                "required": ["project", "name"],
            },
            "output": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "project": {"type": "string"}, "url": {"type": "string"}},
            },
        },
        "update_task": {
            "input": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
            "output": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "url": {"type": "string"}},
            },
        },
        "list_tasks": {
            "input": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"}, "limit": {"type": "integer", "default": 50},
                },
                "required": ["project"],
            },
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "assignee": {"type": "string"}, "due_on": {"type": "string"}, "completed": {"type": "boolean"}},
                },
            },
        },
        "add_comment": {
            "input": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["task_id", "text"],
            },
            "output": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "task_id": {"type": "string"}},
            },
        },
    },
},
```

**Step 6: Run all tests**

Run: `pytest tests/cogos/capabilities/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/cogos/capabilities/asana_cap.py src/cogos/capabilities/__init__.py tests/cogos/capabilities/test_asana_cap.py
git commit -m "feat(capabilities): add AsanaCapability with task CRUD"
```

---

### Task 6: GitHubCapability

**Files:**
- Create: `src/cogos/capabilities/github_cap.py`
- Test: `tests/cogos/capabilities/test_github_cap.py`
- Modify: `src/cogos/capabilities/__init__.py`

Note: file is `github_cap.py` to avoid shadowing the `github` package.

**Step 1: Write the failing tests**

```python
"""Tests for GitHubCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
from uuid import uuid4

import pytest

from cogos.capabilities.github_cap import (
    Contribution,
    GitHubCapability,
    GitHubError,
    RepoDetail,
    RepoSummary,
    UserProfile,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScoping:
    def test_unscoped_allows_all(self, repo, pid):
        cap = GitHubCapability(repo, pid)
        cap._check("search_repos")

    def test_scoped_ops_denies(self, repo, pid):
        cap = GitHubCapability(repo, pid).scope(ops=["get_user"])
        with pytest.raises(PermissionError):
            cap._check("search_repos")

    def test_narrow_intersects_ops(self, repo, pid):
        cap = GitHubCapability(repo, pid)
        s1 = cap.scope(ops=["search_repos", "get_user", "get_repo"])
        s2 = s1.scope(ops=["get_user", "list_contributions"])
        assert s2._scope["ops"] == ["get_user"]

    def test_narrow_intersects_orgs(self, repo, pid):
        cap = GitHubCapability(repo, pid)
        s1 = cap.scope(orgs=["org-a", "org-b"])
        s2 = s1.scope(orgs=["org-b", "org-c"])
        assert s2._scope["orgs"] == ["org-b"]


class TestGetUser:
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value="ghp_test")
    def test_get_user_success(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        mock_user = MagicMock()
        mock_user.login = "octocat"
        mock_user.name = "The Octocat"
        mock_user.bio = "GitHub mascot"
        mock_user.company = "GitHub"
        mock_user.location = "San Francisco"
        mock_user.public_repos = 42
        mock_user.followers = 1000
        mock_user.html_url = "https://github.com/octocat"

        with patch("cogos.capabilities.github_cap.Github") as MockGithub:
            mock_gh = MagicMock()
            mock_gh.get_user.return_value = mock_user
            MockGithub.return_value = mock_gh

            result = cap.get_user("octocat")
            assert isinstance(result, UserProfile)
            assert result.login == "octocat"
            assert result.followers == 1000

    @patch("cogos.capabilities.github_cap.fetch_secret", side_effect=RuntimeError("no key"))
    def test_get_user_missing_key(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        result = cap.get_user("anyone")
        assert isinstance(result, GitHubError)


class TestSearchRepos:
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value="ghp_test")
    def test_search_repos_success(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        mock_repo = MagicMock()
        mock_repo.full_name = "octocat/hello-world"
        mock_repo.description = "A test repo"
        mock_repo.stargazers_count = 100
        mock_repo.language = "Python"
        mock_repo.html_url = "https://github.com/octocat/hello-world"

        with patch("cogos.capabilities.github_cap.Github") as MockGithub:
            mock_gh = MagicMock()
            mock_gh.search_repositories.return_value = [mock_repo]
            MockGithub.return_value = mock_gh

            results = cap.search_repos("hello world", limit=5)
            assert len(results) == 1
            assert isinstance(results[0], RepoSummary)
            assert results[0].full_name == "octocat/hello-world"


class TestGetRepo:
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value="ghp_test")
    def test_get_repo_success(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        mock_repo = MagicMock()
        mock_repo.full_name = "octocat/hello-world"
        mock_repo.description = "A test repo"
        mock_repo.stargazers_count = 100
        mock_repo.forks_count = 50
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = ["python", "hello"]
        mock_repo.html_url = "https://github.com/octocat/hello-world"
        mock_readme = MagicMock()
        mock_readme.decoded_content = b"# Hello World\n\nThis is a test readme with some content."
        mock_repo.get_readme.return_value = mock_readme

        with patch("cogos.capabilities.github_cap.Github") as MockGithub:
            mock_gh = MagicMock()
            mock_gh.get_repo.return_value = mock_repo
            MockGithub.return_value = mock_gh

            result = cap.get_repo("octocat", "hello-world")
            assert isinstance(result, RepoDetail)
            assert result.stars == 100
            assert result.forks == 50
            assert "hello" in result.topics


class TestListContributions:
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value="ghp_test")
    def test_list_contributions_success(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        mock_event = MagicMock()
        mock_event.type = "PushEvent"
        mock_event.repo.name = "octocat/hello-world"
        mock_event.created_at.isoformat.return_value = "2026-03-01T00:00:00"

        with patch("cogos.capabilities.github_cap.Github") as MockGithub:
            mock_gh = MagicMock()
            mock_user = MagicMock()
            mock_user.get_events.return_value = [mock_event]
            mock_gh.get_user.return_value = mock_user
            MockGithub.return_value = mock_gh

            results = cap.list_contributions("octocat", limit=10)
            assert len(results) == 1
            assert isinstance(results[0], Contribution)
            assert results[0].repo == "octocat/hello-world"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/cogos/capabilities/test_github_cap.py -v`
Expected: FAIL — ImportError

**Step 3: Write implementation**

```python
"""GitHub capability — read GitHub data via PyGithub."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    from github import Github
except ImportError:
    Github = None  # type: ignore[assignment,misc]


# ── IO Models ────────────────────────────────────────────────


class RepoSummary(BaseModel):
    full_name: str
    description: str = ""
    stars: int = 0
    language: str = ""
    url: str


class UserProfile(BaseModel):
    login: str
    name: str = ""
    bio: str = ""
    company: str = ""
    location: str = ""
    public_repos: int = 0
    followers: int = 0
    url: str


class Contribution(BaseModel):
    repo: str
    type: str
    title: str = ""
    date: str = ""
    url: str = ""


class RepoDetail(BaseModel):
    full_name: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    language: str = ""
    topics: list[str] = []
    readme_excerpt: str = ""
    url: str


class GitHubError(BaseModel):
    error: str


# ── Event type mapping ───────────────────────────────────────

_EVENT_TYPE_MAP = {
    "PushEvent": "commit",
    "PullRequestEvent": "pr",
    "IssuesEvent": "issue",
    "PullRequestReviewEvent": "review",
    "CreateEvent": "create",
    "ForkEvent": "fork",
    "WatchEvent": "star",
}

# ── Capability ───────────────────────────────────────────────

SECRET_KEY = "cogos/github-token"
_README_EXCERPT_LEN = 500


class GitHubCapability(Capability):
    """Read-only GitHub data access.

    Usage:
        github.get_user("octocat")
        github.search_repos("machine learning python")
        github.get_repo("owner", "repo")
        github.list_contributions("octocat")
    """

    ALL_OPS = {"search_repos", "get_user", "list_contributions", "get_repo"}

    def __init__(self, repo, process_id) -> None:
        super().__init__(repo, process_id)
        self._api_key: str | None = None

    def _get_client(self):
        if self._api_key is None:
            self._api_key = fetch_secret(SECRET_KEY)
        return Github(self._api_key)

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        for key in ("ops", "orgs"):
            old = existing.get(key)
            new = requested.get(key)
            if old is not None and new is not None:
                result[key] = [v for v in old if v in new]
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        # query_budget — min
        old_b = existing.get("query_budget")
        new_b = requested.get("query_budget")
        if old_b is not None and new_b is not None:
            result["query_budget"] = min(old_b, new_b)
        elif old_b is not None:
            result["query_budget"] = old_b
        elif new_b is not None:
            result["query_budget"] = new_b
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")

    def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary] | GitHubError:
        """Search GitHub repositories."""
        self._check("search_repos")
        try:
            gh = self._get_client()
            repos = gh.search_repositories(query)
            return [
                RepoSummary(
                    full_name=r.full_name,
                    description=r.description or "",
                    stars=r.stargazers_count,
                    language=r.language or "",
                    url=r.html_url,
                )
                for r in list(repos)[:limit]
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_user(self, username: str) -> UserProfile | GitHubError:
        """Get a GitHub user profile."""
        self._check("get_user")
        try:
            gh = self._get_client()
            user = gh.get_user(username)
            return UserProfile(
                login=user.login,
                name=user.name or "",
                bio=user.bio or "",
                company=user.company or "",
                location=user.location or "",
                public_repos=user.public_repos,
                followers=user.followers,
                url=user.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    def list_contributions(self, username: str, limit: int = 30) -> list[Contribution] | GitHubError:
        """List recent public activity for a user."""
        self._check("list_contributions")
        try:
            gh = self._get_client()
            user = gh.get_user(username)
            events = list(user.get_events())[:limit]
            return [
                Contribution(
                    repo=e.repo.name,
                    type=_EVENT_TYPE_MAP.get(e.type, e.type),
                    date=e.created_at.isoformat() if e.created_at else "",
                )
                for e in events
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_repo(self, owner: str, name: str) -> RepoDetail | GitHubError:
        """Get detailed information about a repository."""
        self._check("get_repo")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{name}")
            readme_excerpt = ""
            try:
                readme = r.get_readme()
                content = readme.decoded_content.decode("utf-8", errors="replace")
                readme_excerpt = content[:_README_EXCERPT_LEN]
            except Exception:
                pass
            return RepoDetail(
                full_name=r.full_name,
                description=r.description or "",
                stars=r.stargazers_count,
                forks=r.forks_count,
                language=r.language or "",
                topics=r.get_topics(),
                readme_excerpt=readme_excerpt,
                url=r.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    def __repr__(self) -> str:
        return "<GitHubCapability search_repos() get_user() list_contributions() get_repo()>"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/cogos/capabilities/test_github_cap.py -v`
Expected: All passed

**Step 5: Register in BUILTIN_CAPABILITIES**

Add to `src/cogos/capabilities/__init__.py`:

```python
{
    "name": "github",
    "description": "Read GitHub user profiles, repositories, and contributions.",
    "handler": "cogos.capabilities.github_cap.GitHubCapability",
    "instructions": (
        "Use github to read GitHub data (read-only).\n"
        "- github.search_repos(query, limit=10) — search repositories\n"
        "- github.get_user(username) — get a user profile\n"
        "- github.list_contributions(username, limit=30) — list recent activity\n"
        "- github.get_repo(owner, name) — get repo details with readme excerpt\n"
        "API key is managed internally. All operations are read-only."
    ),
    "schema": {
        "scope": {
            "properties": {
                "orgs": {"type": "array", "items": {"type": "string"}, "description": "Allowed organizations"},
                "query_budget": {"type": "integer", "description": "Max API queries allowed"},
                "ops": {"type": "array", "items": {"type": "string", "enum": ["search_repos", "get_user", "list_contributions", "get_repo"]}},
            },
        },
        "search_repos": {
            "input": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}, "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"full_name": {"type": "string"}, "description": {"type": "string"}, "stars": {"type": "integer"}, "language": {"type": "string"}, "url": {"type": "string"}},
                },
            },
        },
        "get_user": {
            "input": {
                "type": "object",
                "properties": {"username": {"type": "string"}},
                "required": ["username"],
            },
            "output": {
                "type": "object",
                "properties": {"login": {"type": "string"}, "name": {"type": "string"}, "bio": {"type": "string"}, "company": {"type": "string"}, "location": {"type": "string"}, "public_repos": {"type": "integer"}, "followers": {"type": "integer"}, "url": {"type": "string"}},
            },
        },
        "list_contributions": {
            "input": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"}, "limit": {"type": "integer", "default": 30},
                },
                "required": ["username"],
            },
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"repo": {"type": "string"}, "type": {"type": "string"}, "title": {"type": "string"}, "date": {"type": "string"}, "url": {"type": "string"}},
                },
            },
        },
        "get_repo": {
            "input": {
                "type": "object",
                "properties": {"owner": {"type": "string"}, "name": {"type": "string"}},
                "required": ["owner", "name"],
            },
            "output": {
                "type": "object",
                "properties": {"full_name": {"type": "string"}, "description": {"type": "string"}, "stars": {"type": "integer"}, "forks": {"type": "integer"}, "language": {"type": "string"}, "topics": {"type": "array"}, "readme_excerpt": {"type": "string"}, "url": {"type": "string"}},
            },
        },
    },
},
```

**Step 6: Run all tests**

Run: `pytest tests/cogos/capabilities/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/cogos/capabilities/github_cap.py src/cogos/capabilities/__init__.py tests/cogos/capabilities/test_github_cap.py
git commit -m "feat(capabilities): add GitHubCapability with read-only GitHub data access"
```

---

### Task 7: Update hatch build targets and run final validation

**Files:**
- Modify: `pyproject.toml:48` (packages list — no change needed since capabilities are under `src/cogos` which is already included)

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All pass

**Step 2: Run linter**

Run: `ruff check src/cogos/capabilities/`
Expected: No errors (or fix any that appear)

**Step 3: Run type checker**

Run: `pyright src/cogos/capabilities/`
Expected: Clean or only expected warnings from optional imports

**Step 4: Update todos**

Mark P0 capabilities as done in `docs/todos.md`:
- `[x]` WebSearchCapability
- `[x]` WebFetchCapability
- `[x]` AsanaCapability
- `[x]` GitHubCapability

**Step 5: Final commit**

```bash
git add docs/todos.md
git commit -m "docs: mark P0 capabilities as complete"
```
