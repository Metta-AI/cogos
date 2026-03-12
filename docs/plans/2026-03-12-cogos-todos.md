# CogOS Feature Todos

Missing capabilities and infrastructure needed for the recruiter app (and general CogOS completeness).

## New Capabilities

### P0 — Required for recruiter MVP

- [ ] **WebSearchCapability** — search the web via API (e.g., Brave Search, Tavily, or SerpAPI). Methods: `search(query, limit) -> list[SearchResult]`. Scopeable by domain allowlist or query budget.

- [ ] **WebFetchCapability** — fetch and extract content from URLs. Methods: `fetch(url) -> PageContent`, `extract_text(url) -> str`. Needed for reading GitHub profiles, Substack posts, Twitter threads. Scopeable by domain allowlist.

- [ ] **AsanaCapability** — create and manage Asana tasks. Methods: `create_task(project, name, notes, ...) -> Task`, `update_task(task_id, ...) -> Task`, `list_tasks(project, ...) -> list[Task]`, `add_comment(task_id, text)`. Scopeable by project/workspace. Uses PAT from secrets.

- [ ] **GitHubCapability** — read GitHub data. Methods: `search_repos(query) -> list[Repo]`, `get_user(username) -> UserProfile`, `list_contributions(username) -> list[Contribution]`, `get_repo(owner, name) -> RepoDetail`. Read-only, scopeable by org/query budget.

### P1 — Required for full recruiter experience

- [ ] **TwitterCapability** — read Twitter/X data. Methods: `search(query) -> list[Tweet]`, `get_user(handle) -> UserProfile`, `get_timeline(handle, limit) -> list[Tweet]`. Read-only. API access may be expensive — consider web scraping fallback via WebFetchCapability.

- [ ] **HtmlRenderCapability** — render data into standalone HTML reports. Methods: `render(template, data) -> str`. Could use Jinja2 templates stored in the file store. The `profile` process needs this to generate candidate deep-dive pages.

### P2 — Nice to have

- [ ] **SubstackCapability** — dedicated Substack content extraction (may be covered by WebFetchCapability + parsing, but a dedicated cap could handle newsletter discovery, subscriber counts, post history).

## Capability Infrastructure Improvements

- [ ] **Rate limiting / budgets** — capabilities that call external APIs need per-run and per-process rate limits. The recruiter will make many API calls; without budgets, a runaway discover process could burn API quotas. Could be implemented as a `budget` field on ProcessCapability with the capability checking remaining quota before each call.

- [ ] **Async/batch tool execution** — `discover` needs to make many API calls per run. Currently the executor runs tools sequentially in the converse loop. Consider supporting batch tool calls or parallel execution within `run_code` (asyncio support in the sandbox).

- [ ] **Structured output from processes** — processes currently return results as free text in the run record. The recruiter needs `discover` to return structured candidate data to the root process. Consider a typed `run.output` field or convention for writing structured results to a known file path.

## Dashboard Extensions

- [ ] **App-specific dashboard views** — the recruiter needs custom views (pipeline, candidate detail, evolution log, criteria editor) beyond the current generic process/file/event views. Need a mechanism for apps to register custom dashboard pages — either:
  - Convention-based: app writes HTML/React components to a known file path
  - Config-based: app declares dashboard routes in a manifest file
  - Template-based: app stores Jinja2 templates that the dashboard renders

- [ ] **Inline HTML rendering** — dashboard needs to render candidate `.html` reports inline in the candidate detail view.

- [ ] **Free-form feedback input** — dashboard candidate detail page needs a text input that writes to the app's feedback log. This is a general pattern (user → event → process) that could be reusable.

- [ ] **File editing in dashboard** — criteria editor view needs to let users edit `.md` and `.json` files directly in the dashboard and save them back to the file store (treated as manual feedback).

## Event System Extensions

- [ ] **Discord response routing** — when `present` asks a question on Discord, the response needs to be routed back to the right process/context. Currently Discord messages come in as generic `discord:*` events. Need a way to correlate a response with the question that prompted it (e.g., thread-based routing: ask in a thread, responses in that thread route to the originating process).

- [ ] **Feedback event type** — standardize a `feedback:candidate` event type so dashboard input and Discord responses flow through the same pipeline. Payload: `{candidate, text, source: "discord"|"dashboard", timestamp}`.

## Process Model Extensions

- [ ] **Process self-modification** — `evolve` needs to modify other processes' attached files (criteria, strategy, sourcer docs) and potentially their code. Currently a process can write to its own scoped files via `me`, but modifying another process's context requires the `files` capability with the right scope. Need to verify this works and document the pattern.

- [ ] **Process templates / spawning from files** — the root `recruiter` process spawns `discover`, `present`, `profile`, `evolve` with specific capabilities and attached files. This is repetitive. Consider a process template mechanism where a file describes the process spec (name, mode, capabilities, attached files) and `procs.spawn_from_template(key)` creates it.

## Security / Governance

- [ ] **Approval gates** — `evolve` posts changes to Discord and waits for approval. This is a general pattern (process proposes action, human approves). Currently no built-in approval mechanism. Options:
  - Process writes proposal to a file, emits event, suspends itself. Human approves via dashboard/Discord, which emits approval event, process resumes.
  - Simpler: process asks on Discord, polls `discord.receive()` for the response on next run.

- [ ] **Audit trail for self-modification** — `evolution.md` is app-level. Consider CogOS-level audit logging for file writes that modify process behavior (criteria, strategy, code files). Could be automatic via the file versioning system — every write creates a version with source attribution.

## Image / Deployment

- [ ] **Recruiter app image** — package the recruiter's initial files (criteria.md, rubric.json, diagnosis.md, strategy.md, sourcer/*.md) as a CogOS image that can be loaded into a cogent. Follow the existing `images/cogent-v1/` pattern.

- [ ] **Secrets provisioning** — recruiter needs API keys for GitHub, Twitter, web search, Asana. These need to be provisioned via the secrets capability. Document the required secrets and add them to the image setup.
