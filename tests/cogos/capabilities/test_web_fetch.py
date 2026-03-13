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
