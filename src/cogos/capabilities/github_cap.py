"""GitHub capability — read GitHub data via PyGithub."""

from __future__ import annotations

import logging
from datetime import datetime

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


class CommitSummary(BaseModel):
    sha: str
    message: str
    author: str = ""
    date: str = ""
    url: str = ""


class CommitDetail(BaseModel):
    sha: str
    message: str
    author: str = ""
    date: str = ""
    files: list[str] = []
    additions: int = 0
    deletions: int = 0
    url: str = ""


class BranchSummary(BaseModel):
    name: str
    protected: bool = False


class CommitComparison(BaseModel):
    ahead_by: int = 0
    behind_by: int = 0
    total_commits: int = 0
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0
    url: str = ""


class PullRequestSummary(BaseModel):
    number: int
    title: str
    state: str
    author: str = ""
    merged: bool = False
    merged_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    url: str = ""


class PullRequestDetail(BaseModel):
    number: int
    title: str
    body: str = ""
    state: str
    author: str = ""
    mergeable: bool | None = None
    merged: bool = False
    review_state: str = ""
    ci_status: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    created_at: str = ""
    updated_at: str = ""
    url: str = ""


class ReviewSummary(BaseModel):
    user: str = ""
    state: str = ""
    body: str = ""
    submitted_at: str = ""


class PRFileSummary(BaseModel):
    filename: str
    status: str = ""
    additions: int = 0
    deletions: int = 0


class IssueSummary(BaseModel):
    number: int
    title: str
    state: str
    author: str = ""
    labels: list[str] = []
    assignee: str = ""
    created_at: str = ""
    url: str = ""


class IssueDetail(BaseModel):
    number: int
    title: str
    body: str = ""
    state: str
    author: str = ""
    labels: list[str] = []
    assignee: str = ""
    comments_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    url: str = ""


class WorkflowRunSummary(BaseModel):
    id: int
    name: str = ""
    status: str = ""
    conclusion: str = ""
    branch: str = ""
    event: str = ""
    created_at: str = ""
    url: str = ""


class WorkflowRunDetail(BaseModel):
    id: int
    name: str = ""
    status: str = ""
    conclusion: str = ""
    branch: str = ""
    event: str = ""
    jobs: list[dict] = []
    created_at: str = ""
    updated_at: str = ""
    url: str = ""


class ReleaseSummary(BaseModel):
    tag_name: str
    name: str = ""
    body: str = ""
    draft: bool = False
    prerelease: bool = False
    published_at: str = ""
    url: str = ""


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

    ALL_OPS = {
        "search_repos", "get_user", "list_contributions", "get_repo", "list_org_repos",
        "list_commits", "get_commit", "list_branches", "compare_commits",
        "list_pull_requests", "get_pull_request", "list_pr_reviews", "list_pr_files",
        "list_issues", "get_issue",
        "list_workflow_runs", "get_workflow_run",
        "list_releases", "get_latest_release",
    }

    def __init__(self, repo, process_id, **kwargs) -> None:
        super().__init__(repo, process_id, **kwargs)
        self._client_instance = None

    def _get_client(self):
        if self._client_instance is not None:
            return self._client_instance
        secret_raw = fetch_secret(SECRET_KEY, secrets_provider=self._secrets_provider)
        import json as _json
        secret = _json.loads(secret_raw)
        secret_type = secret.get("type", "token")
        if secret_type == "github_app" and secret.get("private_key"):
            # GitHub App auth — generate installation token from private key
            app_id = int(secret["app_id"])
            private_key = secret["private_key"]
            installation_id = int(secret["installation_id"])
            app_auth = Auth.AppAuth(app_id, private_key)
            gh = Github(auth=app_auth.get_installation_auth(installation_id))
        else:
            # Personal access token or pre-generated token
            token = secret.get("access_token") or secret_raw
            gh = Github(auth=Auth.Token(token))
        self._client_instance = gh
        return gh

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

    # ── Commits & branches ───────────────────────────────────

    def list_commits(
        self,
        owner: str,
        repo: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        author: str | None = None,
        branch: str | None = None,
        limit: int = 30,
    ) -> list[CommitSummary] | GitHubError:
        """List commits for a repository."""
        self._check("list_commits")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            kwargs: dict = {}
            if branch:
                kwargs["sha"] = branch
            if since:
                kwargs["since"] = since
            if until:
                kwargs["until"] = until
            if author:
                kwargs["author"] = author
            commits = r.get_commits(**kwargs)
            return [
                CommitSummary(
                    sha=c.sha,
                    message=c.commit.message.split("\n", 1)[0],
                    author=(c.commit.author.name if c.commit.author else ""),
                    date=(c.commit.author.date.isoformat() if c.commit.author and c.commit.author.date else ""),
                    url=c.html_url,
                )
                for c in list(commits)[:limit]
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_commit(self, owner: str, repo: str, sha: str) -> CommitDetail | GitHubError:
        """Get detailed info for a single commit."""
        self._check("get_commit")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            c = r.get_commit(sha)
            return CommitDetail(
                sha=c.sha,
                message=c.commit.message,
                author=(c.commit.author.name if c.commit.author else ""),
                date=(c.commit.author.date.isoformat() if c.commit.author and c.commit.author.date else ""),
                files=[f.filename for f in c.files] if c.files else [],
                additions=c.stats.additions if c.stats else 0,
                deletions=c.stats.deletions if c.stats else 0,
                url=c.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    def list_branches(self, owner: str, repo: str) -> list[BranchSummary] | GitHubError:
        """List branches in a repository."""
        self._check("list_branches")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            return [
                BranchSummary(name=b.name, protected=b.protected)
                for b in r.get_branches()
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> CommitComparison | GitHubError:
        """Compare two commits or branches."""
        self._check("compare_commits")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            cmp = r.compare(base, head)
            return CommitComparison(
                ahead_by=cmp.ahead_by,
                behind_by=cmp.behind_by,
                total_commits=cmp.total_commits,
                files_changed=len(cmp.files) if cmp.files else 0,
                additions=sum(f.additions for f in cmp.files) if cmp.files else 0,
                deletions=sum(f.deletions for f in cmp.files) if cmp.files else 0,
                url=cmp.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    # ── Pull requests ────────────────────────────────────────

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        sort: str = "created",
        limit: int = 30,
    ) -> list[PullRequestSummary] | GitHubError:
        """List pull requests for a repository."""
        self._check("list_pull_requests")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            prs = r.get_pulls(state=state, sort=sort, direction="desc")
            return [
                PullRequestSummary(
                    number=p.number,
                    title=p.title,
                    state=p.state,
                    author=(p.user.login if p.user else ""),
                    merged=bool(p.merged),
                    merged_at=(p.merged_at.isoformat() if p.merged_at else ""),
                    created_at=(p.created_at.isoformat() if p.created_at else ""),
                    updated_at=(p.updated_at.isoformat() if p.updated_at else ""),
                    url=p.html_url,
                )
                for p in list(prs)[:limit]
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_pull_request(self, owner: str, repo: str, number: int) -> PullRequestDetail | GitHubError:
        """Get detailed info for a pull request."""
        self._check("get_pull_request")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            p = r.get_pull(number)
            review_state = ""
            try:
                reviews = list(p.get_reviews())
                if reviews:
                    review_state = reviews[-1].state
            except Exception:
                pass
            ci_status = ""
            try:
                last_commit = p.get_commits().reversed[0]
                combined = last_commit.get_combined_status()
                ci_status = combined.state
            except Exception:
                pass
            return PullRequestDetail(
                number=p.number,
                title=p.title,
                body=p.body or "",
                state=p.state,
                author=(p.user.login if p.user else ""),
                mergeable=p.mergeable,
                merged=p.merged,
                review_state=review_state,
                ci_status=ci_status,
                additions=p.additions,
                deletions=p.deletions,
                changed_files=p.changed_files,
                created_at=(p.created_at.isoformat() if p.created_at else ""),
                updated_at=(p.updated_at.isoformat() if p.updated_at else ""),
                url=p.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    def list_pr_reviews(self, owner: str, repo: str, number: int) -> list[ReviewSummary] | GitHubError:
        """List reviews on a pull request."""
        self._check("list_pr_reviews")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            p = r.get_pull(number)
            return [
                ReviewSummary(
                    user=(rv.user.login if rv.user else ""),
                    state=rv.state,
                    body=rv.body or "",
                    submitted_at=(rv.submitted_at.isoformat() if rv.submitted_at else ""),
                )
                for rv in p.get_reviews()
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def list_pr_files(self, owner: str, repo: str, number: int) -> list[PRFileSummary] | GitHubError:
        """List files changed in a pull request."""
        self._check("list_pr_files")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            p = r.get_pull(number)
            return [
                PRFileSummary(
                    filename=f.filename,
                    status=f.status,
                    additions=f.additions,
                    deletions=f.deletions,
                )
                for f in p.get_files()
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    # ── Issues ───────────────────────────────────────────────

    def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        labels: list[str] | None = None,
        assignee: str | None = None,
        limit: int = 30,
    ) -> list[IssueSummary] | GitHubError:
        """List issues for a repository."""
        self._check("list_issues")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            kwargs: dict = {"state": state}
            if labels:
                kwargs["labels"] = [r.get_label(lb) for lb in labels]
            if assignee:
                kwargs["assignee"] = assignee
            issues = r.get_issues(**kwargs)
            return [
                IssueSummary(
                    number=i.number,
                    title=i.title,
                    state=i.state,
                    author=(i.user.login if i.user else ""),
                    labels=[lb.name for lb in i.labels],
                    assignee=(i.assignee.login if i.assignee else ""),
                    created_at=(i.created_at.isoformat() if i.created_at else ""),
                    url=i.html_url,
                )
                for i in list(issues)[:limit]
                if not i.pull_request
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_issue(self, owner: str, repo: str, number: int) -> IssueDetail | GitHubError:
        """Get detailed info for an issue."""
        self._check("get_issue")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            i = r.get_issue(number)
            return IssueDetail(
                number=i.number,
                title=i.title,
                body=i.body or "",
                state=i.state,
                author=(i.user.login if i.user else ""),
                labels=[lb.name for lb in i.labels],
                assignee=(i.assignee.login if i.assignee else ""),
                comments_count=i.comments,
                created_at=(i.created_at.isoformat() if i.created_at else ""),
                updated_at=(i.updated_at.isoformat() if i.updated_at else ""),
                url=i.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    # ── Actions / CI ─────────────────────────────────────────

    def list_workflow_runs(
        self,
        owner: str,
        repo: str,
        *,
        branch: str | None = None,
        status: str | None = None,
        limit: int = 10,
    ) -> list[WorkflowRunSummary] | GitHubError:
        """List GitHub Actions workflow runs."""
        self._check("list_workflow_runs")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            kwargs: dict = {}
            if branch:
                kwargs["branch"] = branch
            if status:
                kwargs["status"] = status
            runs = r.get_workflow_runs(**kwargs)
            return [
                WorkflowRunSummary(
                    id=w.id,
                    name=w.name or "",
                    status=w.status or "",
                    conclusion=w.conclusion or "",
                    branch=w.head_branch or "",
                    event=w.event or "",
                    created_at=(w.created_at.isoformat() if w.created_at else ""),
                    url=w.html_url,
                )
                for w in list(runs)[:limit]
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_workflow_run(self, owner: str, repo: str, run_id: int) -> WorkflowRunDetail | GitHubError:
        """Get detailed info for a workflow run including jobs."""
        self._check("get_workflow_run")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            w = r.get_workflow_run(run_id)
            jobs = []
            try:
                for j in w.jobs():
                    jobs.append({
                        "name": j.name,
                        "status": j.status,
                        "conclusion": j.conclusion or "",
                    })
            except Exception:
                pass
            return WorkflowRunDetail(
                id=w.id,
                name=w.name or "",
                status=w.status or "",
                conclusion=w.conclusion or "",
                branch=w.head_branch or "",
                event=w.event or "",
                jobs=jobs,
                created_at=(w.created_at.isoformat() if w.created_at else ""),
                updated_at=(w.updated_at.isoformat() if w.updated_at else ""),
                url=w.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    # ── Releases ─────────────────────────────────────────────

    def list_releases(self, owner: str, repo: str, *, limit: int = 10) -> list[ReleaseSummary] | GitHubError:
        """List releases for a repository."""
        self._check("list_releases")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            return [
                ReleaseSummary(
                    tag_name=rel.tag_name,
                    name=rel.title or "",
                    body=rel.body or "",
                    draft=rel.draft,
                    prerelease=rel.prerelease,
                    published_at=(rel.published_at.isoformat() if rel.published_at else ""),
                    url=rel.html_url,
                )
                for rel in list(r.get_releases())[:limit]
            ]
        except Exception as exc:
            return GitHubError(error=str(exc))

    def get_latest_release(self, owner: str, repo: str) -> ReleaseSummary | GitHubError:
        """Get the latest published release."""
        self._check("get_latest_release")
        try:
            gh = self._get_client()
            r = gh.get_repo(f"{owner}/{repo}")
            rel = r.get_latest_release()
            return ReleaseSummary(
                tag_name=rel.tag_name,
                name=rel.title or "",
                body=rel.body or "",
                draft=rel.draft,
                prerelease=rel.prerelease,
                published_at=(rel.published_at.isoformat() if rel.published_at else ""),
                url=rel.html_url,
            )
        except Exception as exc:
            return GitHubError(error=str(exc))

    def __repr__(self) -> str:
        ops = " ".join(f"{op}()" for op in sorted(self.ALL_OPS))
        return f"<GitHubCapability {ops}>"
