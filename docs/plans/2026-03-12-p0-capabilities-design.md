# P0 Capabilities Design

Four new capabilities for the recruiter MVP: WebSearch, WebFetch, Asana, GitHub.

## Architecture

Each capability follows the existing pattern:
1. **Capability class** in `src/cogos/capabilities/` — extends `Capability`, implements `_narrow()`, `_check()`, public methods returning Pydantic models
2. **Registration** in `src/cogos/capabilities/__init__.py` — entry in `BUILTIN_CAPABILITIES` with name, handler, instructions, schema
3. **Tests** in `tests/cogos/capabilities/`

### Secret management
Each capability fetches its own API key from AWS SSM/Secrets Manager using boto3 directly (same pattern as `SecretsCapability.get()` internals). No cross-capability dependency. Keys are fetched lazily on first use and cached on the instance.

### Dependencies
New pip dependencies added to `pyproject.toml`:
- `tavily-python` — web search
- `trafilatura` — web content extraction
- `asana` — Asana API
- `PyGithub` — GitHub API

## Capability Specs

### 1. WebSearchCapability

**Name:** `web_search`
**Secret:** `cogos/tavily-api-key`
**Scope:** `domains` (allowlist), `query_budget` (max queries)

**Methods:**
- `search(query, limit=5) -> list[SearchResult] | SearchError`

**Models:**
```python
class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: float

class SearchError(BaseModel):
    error: str
```

### 2. WebFetchCapability

**Name:** `web_fetch`
**Secret:** none (plain HTTP)
**Scope:** `domains` (allowlist)

**Methods:**
- `fetch(url) -> PageContent | FetchError` — raw HTML
- `extract_text(url) -> TextContent | FetchError` — clean text via trafilatura

**Models:**
```python
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
```

### 3. AsanaCapability

**Name:** `asana`
**Secret:** `cogos/asana-pat`
**Scope:** `projects` (allowlist), `ops` (create_task, update_task, list_tasks, add_comment)

**Methods:**
- `create_task(project, name, notes="", assignee=None, due_on=None) -> TaskResult | AsanaError`
- `update_task(task_id, **fields) -> TaskResult | AsanaError`
- `list_tasks(project, limit=50) -> list[TaskSummary] | AsanaError`
- `add_comment(task_id, text) -> CommentResult | AsanaError`

**Models:**
```python
class TaskResult(BaseModel):
    id: str
    name: str
    project: str
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
```

### 4. GitHubCapability

**Name:** `github`
**Secret:** `cogos/github-token`
**Scope:** `orgs` (allowlist), `ops` (search_repos, get_user, list_contributions, get_repo)

**Methods:**
- `search_repos(query, limit=10) -> list[RepoSummary] | GitHubError`
- `get_user(username) -> UserProfile | GitHubError`
- `list_contributions(username, limit=30) -> list[Contribution] | GitHubError`
- `get_repo(owner, name) -> RepoDetail | GitHubError`

**Models:**
```python
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
    type: str  # "commit", "pr", "issue", "review"
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
```

## Secret helper

Extract a shared `_fetch_secret(key)` helper from SecretsCapability internals to avoid duplicating boto3 logic in each capability:

```python
# cogos/capabilities/_secrets_helper.py
def fetch_secret(key: str) -> str:
    """Fetch a secret from SSM or Secrets Manager. Raises RuntimeError on failure."""
```

Each capability calls this in a `_get_api_key()` method that caches the result.

## Scoping patterns

All capabilities use the same intersection patterns:
- **ops:** set intersection (same as ProcsCapability)
- **domains/projects/orgs:** list intersection
- **query_budget:** min of existing and requested
