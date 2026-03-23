# Standup Brief

## Asana

- **workspace_id**: 1209016784099267
- **project_id**: 1213471594342425
- **project_name**: Thread Roadmap
- **sprint_section**: Discover dynamically — list sections and find the one matching the current month/year

## GitHub Repos

- metta-ai/metta
- metta-ai/cogos
- metta-ai/cogents-v1

## Team Members

Map of GitHub login -> Asana display name. Update this as people join/leave.

| GitHub Login         | Asana Name               |
|----------------------|--------------------------|
| daveey               | David Bloomin            |
| nishu-builder        | Nishad Singh             |
| alexsmith            | Alex Smith               |
| subhojeet            | Subhojeet Pramanik       |
| rhiggins             | Richard Higgins          |
| malcolmocean         | Malcolm Ocean            |
| Agentic-Andre        | Andre von Houck          |
| yatharth             | Yatharth Agarwal         |
| martinhess           | Martin Hess              |
| axelkerbec           | Axel Kerbec              |
| noahfarr             | Noah Farr                |
| alexvardakostas      | Alexandros Vardakostas   |

NOTE: GitHub logins marked above are guesses except daveey and nishu-builder
(confirmed from git history). Update these as the bot encounters real logins.

## Discord

- **channel_id**: 1483962779336446114

## Data Sources

Primary: **Pull Requests** (merged = done, open = in progress).
Secondary: **Commits** (supplementary context for non-PR work).

Merged PRs are fetched via `github.list_pull_requests(state="closed")` then
filtered by `detail.merged == True` and recency. Open PRs via `state="open"`.

## Output Format

### View 1: By Thread

For each Asana thread in the sprint section, list merged and in-progress PRs.

```
## By Thread

### Autocurricula
Merged:
- Fix training loop convergence (metta#123) — Axel Kerbec
- Add reward shaping (metta#124) — Axel Kerbec
In progress:
- Implement new curriculum (metta#125) — Noah Farr

### LLMs play CvC
Merged:
- Fix LLM player initialization (metta#200) — Richard Higgins
```

### View 2: By Person

Same data, regrouped by person first.

```
## By Person

### Axel Kerbec
- merged Fix training loop convergence (metta#123) [Autocurricula]
- merged Add reward shaping (metta#124) [Autocurricula]

### Noah Farr
- working on Implement new curriculum (metta#125) [Autocurricula]

### Richard Higgins
- merged Fix LLM player initialization (metta#200) [LLMs play CvC]
```

## Matching PRs to Threads

Use the LLM to judge whether a PR title relates to a thread's topic.
A PR can match at most one thread. If unclear, group under "Untracked".
CI/bot PRs (dependabot, "ci: update", etc.) always go to "Untracked".

## Error Handling

If a data source (Asana, GitHub) is unavailable:
- Print the error clearly
- Continue with whatever data you have
- NEVER fabricate, mock, or invent data
- If both Asana and GitHub fail, post nothing — just log the errors
