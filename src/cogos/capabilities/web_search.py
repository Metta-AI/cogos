"""WebSearch capability — Perplexity, GitHub, and Twitter/X search."""
from __future__ import annotations

import datetime
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
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
        # ops — set intersection (None means "all ops")
        existing_ops = existing.get("ops")
        requested_ops = requested.get("ops")
        old_ops = set(existing_ops) if existing_ops is not None else ALL_OPS
        new_ops = set(requested_ops) if requested_ops is not None else ALL_OPS
        result["ops"] = sorted(old_ops & new_ops)
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
        scope_ops = self._scope.get("ops")
        allowed_ops = set(scope_ops) if scope_ops is not None else ALL_OPS
        if op not in allowed_ops:
            raise PermissionError(
                f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})"
            )

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
            api_key = fetch_secret("cogent/{cogent}/perplexity", field="api_key")
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
        search_type: str = "repositories",
        after_date: str | None = None,
        before_date: str | None = None,
    ) -> GithubSearchResult | SearchError:
        """Search GitHub. search_type: 'repositories'|'issues'|'code'."""
        self._check("search_github")
        try:
            token = fetch_secret("cogent/{cogent}/github", field="access_token")
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
            url = f"https://api.github.com/search/{search_type}?{params}"
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
            bearer = fetch_secret("cogent/{cogent}/twitter", field="bearer_token")
            params: dict[str, Any] = {
                "query": query + " -is:retweet",
                "max_results": 100,
                "tweet.fields": "created_at,public_metrics,author_id",
                "expansions": "author_id",
                "user.fields": "username",
            }
            # Map recency to start_time if no explicit after_date
            if recency and not after_date:
                days = {"day": 1, "week": 7, "month": 30}.get(recency, 7)
                start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
                params["start_time"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            if after_date:
                params["start_time"] = after_date + "T00:00:00Z"
            if before_date:
                params["end_time"] = before_date + "T23:59:59Z"
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
