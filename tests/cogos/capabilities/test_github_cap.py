"""Tests for GitHubCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
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


@pytest.fixture(autouse=True)
def _mock_auth():
    """Patch Auth so tests work without PyGithub installed."""
    with patch("cogos.capabilities.github_cap.Auth", new_callable=MagicMock):
        yield


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


class TestListOrgRepos:
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value="ghp_test")
    def test_list_org_repos_success(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        mock_repo = MagicMock()
        mock_repo.full_name = "metta-ai/metta"
        mock_repo.description = "Training framework"
        mock_repo.stargazers_count = 50
        mock_repo.language = "Python"
        mock_repo.html_url = "https://github.com/metta-ai/metta"

        with patch("cogos.capabilities.github_cap.Github") as MockGithub:
            mock_gh = MagicMock()
            mock_org = MagicMock()
            mock_org.get_repos.return_value = [mock_repo]
            mock_gh.get_organization.return_value = mock_org
            MockGithub.return_value = mock_gh

            results = cap.list_org_repos("metta-ai", limit=10)
            assert len(results) == 1
            assert isinstance(results[0], RepoSummary)
            assert results[0].full_name == "metta-ai/metta"
            mock_org.get_repos.assert_called_once_with(sort="pushed", direction="desc")

    @patch("cogos.capabilities.github_cap.fetch_secret", return_value="ghp_test")
    def test_list_org_repos_error(self, mock_secret, repo, pid):
        cap = GitHubCapability(repo, pid)
        with patch("cogos.capabilities.github_cap.Github") as MockGithub:
            mock_gh = MagicMock()
            mock_gh.get_organization.side_effect = RuntimeError("org not found")
            MockGithub.return_value = mock_gh

            result = cap.list_org_repos("nonexistent")
            assert isinstance(result, GitHubError)

    def test_list_org_repos_scoped_denied(self, repo, pid):
        cap = GitHubCapability(repo, pid).scope(ops=["get_repo"])
        with pytest.raises(PermissionError):
            cap.list_org_repos("metta-ai")


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
