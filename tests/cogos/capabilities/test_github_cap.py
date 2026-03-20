"""Tests for GitHubCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.github_cap import (
    BranchSummary,
    CommitComparison,
    CommitDetail,
    CommitSummary,
    Contribution,
    GitHubCapability,
    GitHubError,
    IssueDetail,
    IssueSummary,
    PRFileSummary,
    PullRequestDetail,
    PullRequestSummary,
    ReleaseSummary,
    RepoDetail,
    RepoSummary,
    ReviewSummary,
    UserProfile,
    WorkflowRunDetail,
    WorkflowRunSummary,
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
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')
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
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')
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
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], RepoSummary)
            assert results[0].full_name == "octocat/hello-world"


class TestGetRepo:
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')
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
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')
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
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], RepoSummary)
            assert results[0].full_name == "metta-ai/metta"
            mock_org.get_repos.assert_called_once_with(sort="pushed", direction="desc")

    @patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')
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
    @patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')
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
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], Contribution)
            assert results[0].repo == "octocat/hello-world"


# ── Commits & branches ──────────────────────────────────────


def _make_mock_commit(sha="abc123", message="fix bug", author_name="dev", date_iso="2026-03-01T00:00:00"):
    c = MagicMock()
    c.sha = sha
    c.html_url = f"https://github.com/o/r/commit/{sha}"
    c.commit.message = message
    c.commit.author.name = author_name
    c.commit.author.date.isoformat.return_value = date_iso
    c.files = [MagicMock(filename="a.py"), MagicMock(filename="b.py")]
    c.stats.additions = 10
    c.stats.deletions = 3
    return c


def _gh_cap(repo, pid):
    return GitHubCapability(repo, pid)


_SECRET_PATCH = patch("cogos.capabilities.github_cap.fetch_secret", return_value='{"type":"token","token":"ghp_test"}')


class TestListCommits:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mc = _make_mock_commit()
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_commits.return_value = [mc]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_commits("o", "r", limit=5)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], CommitSummary)
            assert results[0].sha == "abc123"

    @_SECRET_PATCH
    def test_error(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_gh.get_repo.side_effect = RuntimeError("nope")
            G.return_value = mock_gh
            result = cap.list_commits("o", "r")
            assert isinstance(result, GitHubError)

    def test_scoped_denied(self, repo, pid):
        cap = _gh_cap(repo, pid).scope(ops=["get_user"])
        with pytest.raises(PermissionError):
            cap.list_commits("o", "r")


class TestGetCommit:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mc = _make_mock_commit()
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_commit.return_value = mc
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            result = cap.get_commit("o", "r", "abc123")
            assert isinstance(result, CommitDetail)
            assert result.additions == 10
            assert len(result.files) == 2


class TestListBranches:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mb = MagicMock()
        mb.name = "main"
        mb.protected = True
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_branches.return_value = [mb]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_branches("o", "r")
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], BranchSummary)
            assert results[0].name == "main"
            assert results[0].protected is True


class TestCompareCommits:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        cmp = MagicMock()
        cmp.ahead_by = 3
        cmp.behind_by = 1
        cmp.total_commits = 3
        f1 = MagicMock()
        f1.additions = 10
        f1.deletions = 2
        cmp.files = [f1]
        cmp.html_url = "https://github.com/o/r/compare/a...b"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.compare.return_value = cmp
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            result = cap.compare_commits("o", "r", "main", "feature")
            assert isinstance(result, CommitComparison)
            assert result.ahead_by == 3
            assert result.files_changed == 1


# ── Pull requests ────────────────────────────────────────────


class TestListPullRequests:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mp = MagicMock()
        mp.number = 42
        mp.title = "Add feature"
        mp.state = "open"
        mp.user.login = "dev"
        mp.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        mp.updated_at.isoformat.return_value = "2026-03-02T00:00:00"
        mp.html_url = "https://github.com/o/r/pull/42"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_pulls.return_value = [mp]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_pull_requests("o", "r", limit=5)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], PullRequestSummary)
            assert results[0].number == 42


class TestGetPullRequest:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mp = MagicMock()
        mp.number = 42
        mp.title = "Add feature"
        mp.body = "Description"
        mp.state = "open"
        mp.user.login = "dev"
        mp.mergeable = True
        mp.merged = False
        mp.additions = 50
        mp.deletions = 10
        mp.changed_files = 3
        mp.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        mp.updated_at.isoformat.return_value = "2026-03-02T00:00:00"
        mp.html_url = "https://github.com/o/r/pull/42"
        review = MagicMock()
        review.state = "APPROVED"
        mp.get_reviews.return_value = [review]
        mp.get_commits.return_value.reversed = [MagicMock()]
        mp.get_commits.return_value.reversed[0].get_combined_status.return_value.state = "success"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_pull.return_value = mp
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            result = cap.get_pull_request("o", "r", 42)
            assert isinstance(result, PullRequestDetail)
            assert result.mergeable is True
            assert result.review_state == "APPROVED"


class TestListPRReviews:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        rv = MagicMock()
        rv.user.login = "reviewer"
        rv.state = "APPROVED"
        rv.body = "LGTM"
        rv.submitted_at.isoformat.return_value = "2026-03-02T00:00:00"
        mp = MagicMock()
        mp.get_reviews.return_value = [rv]
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_pull.return_value = mp
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_pr_reviews("o", "r", 42)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], ReviewSummary)
            assert results[0].state == "APPROVED"


class TestListPRFiles:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        f = MagicMock()
        f.filename = "src/main.py"
        f.status = "modified"
        f.additions = 10
        f.deletions = 2
        mp = MagicMock()
        mp.get_files.return_value = [f]
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_pull.return_value = mp
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_pr_files("o", "r", 42)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], PRFileSummary)
            assert results[0].filename == "src/main.py"


# ── Issues ───────────────────────────────────────────────────


class TestListIssues:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mi = MagicMock()
        mi.number = 10
        mi.title = "Bug report"
        mi.state = "open"
        mi.user.login = "reporter"
        label = MagicMock()
        label.name = "bug"
        mi.labels = [label]
        mi.assignee.login = "dev"
        mi.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        mi.html_url = "https://github.com/o/r/issues/10"
        mi.pull_request = None
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = [mi]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_issues("o", "r", limit=5)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], IssueSummary)
            assert results[0].number == 10
            assert results[0].labels == ["bug"]

    @_SECRET_PATCH
    def test_filters_out_pull_requests(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        issue = MagicMock()
        issue.number = 10
        issue.title = "Real issue"
        issue.state = "open"
        issue.user.login = "u"
        issue.labels = []
        issue.assignee = None
        issue.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        issue.html_url = "https://github.com/o/r/issues/10"
        issue.pull_request = None
        pr_as_issue = MagicMock()
        pr_as_issue.pull_request = {"url": "..."}
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_issues.return_value = [issue, pr_as_issue]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_issues("o", "r")
            assert not isinstance(results, GitHubError)
            assert len(results) == 1


class TestGetIssue:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mi = MagicMock()
        mi.number = 10
        mi.title = "Bug report"
        mi.body = "Details here"
        mi.state = "open"
        mi.user.login = "reporter"
        mi.labels = []
        mi.assignee = None
        mi.comments = 5
        mi.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        mi.updated_at.isoformat.return_value = "2026-03-02T00:00:00"
        mi.html_url = "https://github.com/o/r/issues/10"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_issue.return_value = mi
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            result = cap.get_issue("o", "r", 10)
            assert isinstance(result, IssueDetail)
            assert result.comments_count == 5


# ── Actions / CI ─────────────────────────────────────────────


class TestListWorkflowRuns:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mw = MagicMock()
        mw.id = 999
        mw.name = "CI"
        mw.status = "completed"
        mw.conclusion = "success"
        mw.head_branch = "main"
        mw.event = "push"
        mw.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        mw.html_url = "https://github.com/o/r/actions/runs/999"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_workflow_runs.return_value = [mw]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_workflow_runs("o", "r", limit=5)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], WorkflowRunSummary)
            assert results[0].conclusion == "success"


class TestGetWorkflowRun:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mw = MagicMock()
        mw.id = 999
        mw.name = "CI"
        mw.status = "completed"
        mw.conclusion = "success"
        mw.head_branch = "main"
        mw.event = "push"
        job = MagicMock()
        job.name = "build"
        job.status = "completed"
        job.conclusion = "success"
        mw.jobs.return_value = [job]
        mw.created_at.isoformat.return_value = "2026-03-01T00:00:00"
        mw.updated_at.isoformat.return_value = "2026-03-01T00:05:00"
        mw.html_url = "https://github.com/o/r/actions/runs/999"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_workflow_run.return_value = mw
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            result = cap.get_workflow_run("o", "r", 999)
            assert isinstance(result, WorkflowRunDetail)
            assert len(result.jobs) == 1
            assert result.jobs[0]["name"] == "build"


# ── Releases ─────────────────────────────────────────────────


class TestListReleases:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mr = MagicMock()
        mr.tag_name = "v1.0.0"
        mr.title = "First release"
        mr.body = "Release notes"
        mr.draft = False
        mr.prerelease = False
        mr.published_at.isoformat.return_value = "2026-03-01T00:00:00"
        mr.html_url = "https://github.com/o/r/releases/tag/v1.0.0"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_releases.return_value = [mr]
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            results = cap.list_releases("o", "r", limit=5)
            assert not isinstance(results, GitHubError)
            assert len(results) == 1
            assert isinstance(results[0], ReleaseSummary)
            assert results[0].tag_name == "v1.0.0"


class TestGetLatestRelease:
    @_SECRET_PATCH
    def test_success(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        mr = MagicMock()
        mr.tag_name = "v2.0.0"
        mr.title = "Latest"
        mr.body = "Notes"
        mr.draft = False
        mr.prerelease = False
        mr.published_at.isoformat.return_value = "2026-03-15T00:00:00"
        mr.html_url = "https://github.com/o/r/releases/tag/v2.0.0"
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_repo = MagicMock()
            mock_repo.get_latest_release.return_value = mr
            mock_gh.get_repo.return_value = mock_repo
            G.return_value = mock_gh
            result = cap.get_latest_release("o", "r")
            assert isinstance(result, ReleaseSummary)
            assert result.tag_name == "v2.0.0"

    @_SECRET_PATCH
    def test_error(self, _s, repo, pid):
        cap = _gh_cap(repo, pid)
        with patch("cogos.capabilities.github_cap.Github") as G:
            mock_gh = MagicMock()
            mock_gh.get_repo.side_effect = RuntimeError("not found")
            G.return_value = mock_gh
            result = cap.get_latest_release("o", "r")
            assert isinstance(result, GitHubError)
