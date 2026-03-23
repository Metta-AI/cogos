@{mnt/boot/standup/brief.md}

# Instructions

Execute each step using `run_code`. Never skip steps. Never fabricate data.

## Step 1: Find the current sprint section and list threads

Use `asana.list_sections(project_id)` to get all sections. Find the one whose
name contains the current month name (e.g. "March") and year (e.g. "2026").
Do NOT hardcode the month or year — derive them from `datetime.date.today()`.

Then `asana.list_tasks(project_id)` and for each task, `asana.get_task(t.id)`.
Keep tasks where `d.section` contains the sprint section name. Store them as
`threads` — a list of `{"name": ..., "assignee": ...}`.

If Asana fails, set `threads = []` and print the error.

## Step 2: Get merged and open PRs

For each repo in `[("metta-ai", "metta"), ("metta-ai", "cogos"), ("metta-ai", "cogents-v1")]`:

1. `github.list_pull_requests(owner, repo, state="closed", sort="updated", limit=50)`
   Filter to PRs where `pr.merged` is true and `pr.merged_at` is non-empty.
   Store as `merged_prs[repo_name]` — list of dicts with number, title, author, merged_at.

2. `github.list_pull_requests(owner, repo, state="open", limit=50)`
   Store as `open_prs[repo_name]` — list of dicts with number, title, author.

If GitHub fails, set empty lists and print the error.

**Important**: The `merged` and `merged_at` fields are on the PR summary object
directly — do NOT call `get_pull_request()` for each PR.

## Step 3: Get commits (supplementary)

For each repo: `github.list_commits(owner, repo, since=24h_ago, limit=100)`.
Filter out merge commits (`message.startswith("Merge ")`) and CI commits
(`message.startswith("ci: ")`). Store as `all_commits[repo_name]`.

## Step 4: Match, build report, save, and post

If both Asana and GitHub failed entirely, print an error summary and stop.
Do NOT generate a fake report. You may post a brief error notice to Discord.

Otherwise, in a SINGLE `run_code` call:

**Matching**: For each merged PR and open PR, decide which Asana thread it best
matches based on PR title vs thread name. Use the name_map from the brief to
convert GitHub logins to display names. CI/bot PRs go to "Untracked".

**Report format** (two views):

```
# Daily Standup — YYYY-MM-DD

## By Thread

### Thread Name
Merged:
- PR title (repo#number) — Author Name
In progress:
- PR title (repo#number) — Author Name

### Untracked
Merged:
- ...

## By Person

### Author Name
- merged PR title (repo#number) [Thread Name]
- working on PR title (repo#number) [Thread Name]

---
N merged PRs, M open PRs across 3 repos
```

**Save**: `disk.get("reports/" + today + ".md").write(report)`

**Post**: `discord.create_thread(channel_id, "Standup — " + today, report)`.
If that fails, fall back to `discord.send(channel_id, report)`.
The channel_id is "1483962779336446114".
