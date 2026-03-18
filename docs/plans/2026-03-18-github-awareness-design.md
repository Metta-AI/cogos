# GitHub Awareness Design

## Goal

Give cogents awareness of the MettaAI GitHub organization, external repos of interest, and their own source repository. Knowledge is maintained automatically via periodic scanning and on-demand discovery.

## Data Layout

```
whoami/
  source_repo.md                        # Pointer to metta-ai/cogents-v1

data/
  github/
    repos.md                            # Monitored repos list
    metta-ai/
      cogents-v1/
        summary.md                      # Enhanced depth (architecture, capabilities, executor, includes)
        recent_changes.md
      metta/
        summary.md
        recent_changes.md
      ...
    other-org/
      specific-repo/
        summary.md
        recent_changes.md
```

### `repos.md`

Seeded in the image with initial entries. Discovery coglet appends new repos at runtime.

```markdown
# Repos to monitor

## Organizations (all active repos)
metta-ai/*

## Specific repos
some-org/interesting-project
another-org/cool-tool
```

- `org/*` — scanner lists org repos via GitHub API, filters to those with commits in last 3 months
- `org/repo` — always scanned regardless of activity

### `whoami/source_repo.md`

Lightweight identity-level pointer. Deep knowledge lives in `data/github/metta-ai/cogents-v1/`.

```markdown
# Source Repository

repo: metta-ai/cogents-v1

This cogent runs on CogOS, the runtime defined in this repository.
For detailed architecture and recent changes, see data/github/metta-ai/cogents-v1/
```

### `summary.md` (per repo, ~30-50 lines)

```markdown
# metta-ai/metta

Last scanned: 2026-03-18

## Purpose
Reinforcement learning training framework for multi-agent environments.

## Key Details
- Language: Python
- Maintainers: @daveey, @contributor2
- Related repos: metta-ai/cogents-v1 (uses metta for training)

## Architecture
- src/metta/ — core training loop
- configs/ — experiment configurations
- tools/ — CLI utilities (run.py, eval.py)

## Key Abstractions
- Agent — policy wrapper
- Environment — simulation interface
```

Enhanced depth for `cogents-v1`: includes capability APIs, executor flow, include system, cog/coglet pattern.

### `recent_changes.md` (accumulating, compacted at ~200 lines)

```markdown
# Recent Changes: metta-ai/metta

## 2026-03-18
- Added new curriculum training support in src/metta/curriculum/
- Fixed checkpoint loading for multi-GPU setups
- Updated dependency: torch 2.5 → 2.6

## 2026-03-11
- Refactored evaluation pipeline for faster episode rollouts
- New CLI command: `metta eval --compare`
```

## GitHub Cog

```
images/cogent-v1/apps/github/
├── cog.py              # mode="daemon", capabilities=[github, file, dir]
├── main.md             # Orchestrator: reads repos.md, dispatches scanner coglets
├── scanner/
│   ├── cog.py          # mode="one_shot"
│   └── main.md         # Scans a single repo, writes summary.md + appends recent_changes.md
└── discovery/
    ├── cog.py          # mode="one_shot"
    └── main.md         # On-demand: scans unknown repo, adds to repos.md
```

### Main (daemon, cron-scheduled)

1. Read `data/github/repos.md` — parse `org/*` and `org/repo` entries
2. For `org/*` entries — call `github.search_repos()` to list org repos, filter to active (commits in last 3 months)
3. For `org/repo` entries — include regardless of activity
4. Spawn `scanner` coglet for each repo to scan

### Scanner coglet (one_shot)

1. Receive repo name on `io:stdin`
2. Call `github.get_repo()` — fetch metadata, README, structure, recent commits
3. Write/update `data/github/<org>/<repo>/summary.md`
4. Append dated entry to `data/github/<org>/<repo>/recent_changes.md`
5. If file exceeds ~200 lines, compact older entries
6. If repo is `cogents-v1`: enhanced depth in summary, also update `whoami/source_repo.md`

### Discovery coglet (one_shot)

Triggered via `github:discover` channel when any cogent process encounters an unfamiliar repo.

1. Receive repo name on `github:discover`
2. Scan repo (same logic as scanner coglet)
3. Append repo to `data/github/repos.md` if not already listed

## Capabilities Required

- `github` — `search_repos`, `get_repo` operations
- `file` — read/write summary, recent_changes, repos.md, source_repo.md
- `dir` — create `data/github/<org>/<repo>/` directories

## Integration

Any cogent process can trigger on-demand discovery by sending a message to the `github:discover` channel with a repo name. The github cog subscribes to this channel and spawns a discovery coglet.
