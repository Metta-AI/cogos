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
