"""GitHub capability — read GitHub data via PyGithub."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities._secrets_helper import fetch_secret
from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)

try:
    from github import Auth, Github
except ImportError:
    Auth = None  # type: ignore[assignment,misc]
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


# ── GitHub activity type mapping ─────────────────────────────

_ACTIVITY_TYPE_MAP = {
    "PushEvent": "commit",
    "PullRequestEvent": "pr",
    "IssuesEvent": "issue",
    "PullRequestReviewEvent": "review",
    "CreateEvent": "create",
    "ForkEvent": "fork",
    "WatchEvent": "star",
}

# ── Capability ───────────────────────────────────────────────

SECRET_KEY = "cogent/{cogent}/github"
_README_EXCERPT_LEN = 500


class GitHubCapability(Capability):
    """Read-only GitHub data access.

    Usage:
        github.get_user("octocat")
        github.search_repos("machine learning python")
        github.get_repo("owner", "repo")
        github.list_contributions("octocat")
    """

    ALL_OPS = {"search_repos", "get_user", "list_contributions", "get_repo", "list_org_repos"}

    def __init__(self, repo, process_id) -> None:
        super().__init__(repo, process_id)
        self._api_key: str | None = None

    def _get_client(self):
        if self._api_key is None:
            self._api_key = fetch_secret(SECRET_KEY, field="access_token")
        return Github(auth=Auth.Token(self._api_key))

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
                    type=_ACTIVITY_TYPE_MAP.get(e.type, e.type),
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

    def list_org_repos(self, org: str, limit: int = 100) -> list[RepoSummary] | GitHubError:
        """List repositories for a GitHub organization."""
        self._check("list_org_repos")
        try:
            gh = self._get_client()
            organization = gh.get_organization(org)
            repos = organization.get_repos(sort="pushed", direction="desc")
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

    def __repr__(self) -> str:
        return "<GitHubCapability search_repos() get_user() list_contributions() get_repo() list_org_repos()>"
