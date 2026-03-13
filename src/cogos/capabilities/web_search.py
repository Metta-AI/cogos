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

SECRET_KEY = "cogent/{cogent}/tavily"


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
            self._api_key = fetch_secret(SECRET_KEY, field="api_key")
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
