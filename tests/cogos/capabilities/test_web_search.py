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
        assert "pushed" in url

    def test_appends_before_date_qualifier(self, cap):
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value={"items": []}) as mock_http:
            cap.search_github("my query", before_date="2025-12-31")
        url = mock_http.call_args[0][0]
        assert "2025-12-31" in url
        assert "pushed" in url

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

    def test_uses_all_endpoint_for_before_date(self, cap):
        resp = {"data": [], "includes": {}}
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search_twitter("q", before_date="2025-12-31")
        assert "/search/all" in mock_http.call_args[0][0]

    def test_recency_sets_start_time(self, cap):
        resp = {"data": [], "includes": {}}
        with patch.object(cap, "_get_secret", return_value="t"), \
             patch.object(cap, "_http_json", return_value=resp) as mock_http:
            cap.search_twitter("q", recency="day")
        url = mock_http.call_args[0][0]
        assert "start_time" in url
        assert "/search/recent" in url  # recency alone doesn't trigger /all

    def test_returns_error_on_exception(self, cap):
        with patch.object(cap, "_get_secret", side_effect=Exception("x")):
            result = cap.search_twitter("q")
        assert isinstance(result, SearchError)
