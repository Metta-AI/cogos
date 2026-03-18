# GitHub Awareness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give cogents awareness of MettaAI repos, external repos of interest, and their own source repo via a GitHub scanner cog that maintains per-repo knowledge files.

**Architecture:** A `github` cog runs as a daemon, subscribing to `system:tick:hour` and `github:discover`. On each hourly tick it checks if a daily scan is due. It dispatches `scanner` coglets per repo and `discovery` coglets on demand. The GitHub capability is extended with `list_org_repos` to enumerate organization repositories.

**Tech Stack:** Python (cog orchestrator), LLM (scanner/discovery coglets), PyGithub (GitHub API)

---

### Task 1: Extend GitHubCapability with `list_org_repos`

**Files:**
- Modify: `src/cogos/capabilities/github_cap.py`
- Modify: `tests/cogos/capabilities/test_github_cap.py` (create if not exists)

**Step 1: Add `list_org_repos` to `ALL_OPS` and implement the method**

In `src/cogos/capabilities/github_cap.py`, add `"list_org_repos"` to `ALL_OPS` and add:

```python
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
```

**Step 2: Update `__repr__`**

```python
def __repr__(self) -> str:
    return "<GitHubCapability search_repos() get_user() list_contributions() get_repo() list_org_repos()>"
```

**Step 3: Commit**

```bash
git add src/cogos/capabilities/github_cap.py
git commit -m "feat(github): add list_org_repos to GitHubCapability"
```

---

### Task 2: Create `whoami/source_repo.md`

**Files:**
- Create: `images/cogent-v1/whoami/source_repo.md`

**Step 1: Create the static identity file**

```markdown
# Source Repository

repo: metta-ai/cogents-v1

This cogent runs on CogOS, the runtime defined in this repository.
For detailed architecture and recent changes, see data/github/metta-ai/cogents-v1/
```

**Step 2: Commit**

```bash
git add images/cogent-v1/whoami/source_repo.md
git commit -m "feat(github): add whoami/source_repo.md identity pointer"
```

---

### Task 3: Create `data/github/repos.md` seed file

**Files:**
- Create: `images/cogent-v1/files/data/github/repos.md`

Note: Static data files that should exist at boot live under `images/cogent-v1/files/` — they get loaded into the FileStore during image build.

**Step 1: Create the seed repos list**

```markdown
# Repos to monitor

## Organizations (all active repos)
metta-ai/*

## Specific repos
```

**Step 2: Commit**

```bash
git add images/cogent-v1/files/data/github/repos.md
git commit -m "feat(github): add seed repos.md for github scanner"
```

---

### Task 4: Create the GitHub cog config

**Files:**
- Create: `images/cogent-v1/apps/github/cog.py`

**Step 1: Write the cog config**

```python
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=2.0,
    executor="python",
    capabilities=[
        "me", "procs", "dir", "file", "github",
        "channels", "stdlib",
    ],
    handlers=[
        "system:tick:hour",
        "github:discover",
    ],
)
```

**Step 2: Commit**

```bash
git add images/cogent-v1/apps/github/cog.py
git commit -m "feat(github): add github cog config"
```

---

### Task 5: Create the scanner coglet

**Files:**
- Create: `images/cogent-v1/apps/github/scanner/cog.py`
- Create: `images/cogent-v1/apps/github/scanner/main.md`

**Step 1: Write scanner coglet config**

`scanner/cog.py`:
```python
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="one_shot",
    emoji="🔍",
)
```

**Step 2: Write scanner coglet prompt**

`scanner/main.md`:
```markdown
# GitHub Repo Scanner

@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}

You scan a single GitHub repository and update its knowledge files.

## Input

You receive a JSON message on stdin with:
- `repo`: full repo name (e.g., `metta-ai/metta`)
- `is_self_repo`: boolean — true if this is the cogent's own source repo

## Steps

### 1. Fetch repo details

```python
owner, name = repo.split("/")
detail = github.get_repo(owner, name)
if hasattr(detail, 'error'):
    channels.send("io:stderr", "ERROR: " + detail.error)
    exit()
print(detail)
```

### 2. Read existing summary (if any)

```python
existing = data.get("github/" + repo + "/summary.md").read()
if not hasattr(existing, 'error'):
    print("Existing summary:")
    print(existing.content)
```

### 3. Write summary.md

Write a summary with these sections:
- **Purpose**: What the repo does (from README + description)
- **Key Details**: Language, topics, stars, forks
- **Architecture**: Key directories and what they contain (infer from README)
- **Key Abstractions**: Main concepts/patterns (infer from README)
- **Related Repos**: How it relates to other metta-ai repos (if apparent)

Target ~30-50 lines. If `is_self_repo` is true, go deeper (~80-100 lines) — document architecture, capability APIs, executor flow, include system, cog/coglet pattern.

Add `Last scanned: YYYY-MM-DD` at the top.

```python
data.get("github/" + repo + "/summary.md").write(summary_content)
```

### 4. Append to recent_changes.md

Read the existing recent_changes.md. Compare the repo's current state (from README, description, topics) with what's in the existing summary to identify what changed.

Append a dated entry:

```python
import json
today = stdlib.time.strftime("%Y-%m-%d")
entry = "\n## " + today + "\n" + changes_summary + "\n"

existing_changes = data.get("github/" + repo + "/recent_changes.md").read()
if hasattr(existing_changes, 'error'):
    content = "# Recent Changes: " + repo + "\n" + entry
else:
    content = existing_changes.content + entry

# Compact if over 200 lines
lines = content.split("\n")
if len(lines) > 200:
    # Keep header + last 150 lines
    header = lines[0]
    content = header + "\n\n(earlier entries compacted)\n\n" + "\n".join(lines[-150:])

data.get("github/" + repo + "/recent_changes.md").write(content)
```

### 5. Update source_repo.md (if self repo)

If `is_self_repo` is true, also update `whoami/source_repo.md` with a brief refreshed summary:

```python
source_content = "# Source Repository\n\nrepo: " + repo + "\n\n" + brief_self_description
file.write("whoami/source_repo.md", source_content)
```

### 6. Report completion

```python
channels.send("io:stdout", {"repo": repo, "status": "scanned"})
```
```

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/github/scanner/
git commit -m "feat(github): add scanner coglet"
```

---

### Task 6: Create the discovery coglet

**Files:**
- Create: `images/cogent-v1/apps/github/discovery/cog.py`
- Create: `images/cogent-v1/apps/github/discovery/main.md`

**Step 1: Write discovery coglet config**

`discovery/cog.py`:
```python
from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="one_shot",
    emoji="🔎",
)
```

**Step 2: Write discovery coglet prompt**

`discovery/main.md`:
```markdown
# GitHub Repo Discovery

@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}

You scan an unfamiliar GitHub repository on-demand and register it for future monitoring.

## Input

You receive a JSON message on stdin with:
- `repo`: full repo name (e.g., `some-org/some-repo`)

## Steps

### 1. Check if already tracked

```python
repos_content = data.get("github/repos.md").read()
if not hasattr(repos_content, 'error') and repo in repos_content.content:
    print("Repo already in repos.md, scanning anyway for freshness")
```

### 2. Scan the repo

Follow the same scanning logic as the scanner coglet:
- Fetch repo details via `github.get_repo(owner, name)`
- Write `data/github/<org>/<repo>/summary.md`
- Write initial `data/github/<org>/<repo>/recent_changes.md`

### 3. Add to repos.md if not already listed

```python
repos_content = data.get("github/repos.md").read()
if hasattr(repos_content, 'error'):
    content = "# Repos to monitor\n\n## Specific repos\n" + repo + "\n"
else:
    content = repos_content.content
    if repo not in content:
        content = content.rstrip() + "\n" + repo + "\n"
data.get("github/repos.md").write(content)
```

### 4. Report completion

```python
channels.send("io:stdout", {"repo": repo, "status": "discovered"})
```
```

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/github/discovery/
git commit -m "feat(github): add discovery coglet"
```

---

### Task 7: Create the GitHub cog orchestrator

**Files:**
- Create: `images/cogent-v1/apps/github/main.py`

**Step 1: Write the orchestrator**

```python
# GitHub cog orchestrator — Python executor
# Dispatches hourly/daily scans and on-demand discovery to LLM coglets.

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Source repo identity
SOURCE_REPO = "metta-ai/cogents-v1"

# Create coglets
scanner = cog.make_coglet("scanner", entrypoint="main.md",
    files={"main.md": file.read("apps/github/scanner/main.md").content})
discovery = cog.make_coglet("discovery", entrypoint="main.md",
    files={"main.md": file.read("apps/github/discovery/main.md").content})

worker_caps = {
    "github": None, "data": None, "dir": None,
    "file": None, "channels": None, "stdlib": None,
}

if channel == "github:discover":
    # On-demand discovery
    repo = payload.get("repo", "")
    if not repo:
        print("github: discover missing repo in payload")
        exit()
    run = coglet_runtime.run(discovery, procs, capability_overrides=worker_caps)
    run.process().send({"repo": repo})

elif channel == "system:tick:hour":
    # Check if daily scan is due
    last_scan = data.get("github/last_scan.txt").read()
    today = stdlib.time.strftime("%Y-%m-%d")
    if not hasattr(last_scan, 'error') and last_scan.content.strip() == today:
        print("github: already scanned today")
        exit()

    # Read repos.md and build scan list
    repos_content = data.get("github/repos.md").read()
    if hasattr(repos_content, 'error'):
        print("github: repos.md not found")
        exit()

    scan_repos = []
    for line in repos_content.content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("/*"):
            # Org wildcard — list org repos
            org = line[:-2]
            org_repos = github.list_org_repos(org, limit=100)
            if hasattr(org_repos, 'error'):
                print("WARN: list_org_repos " + org + " failed: " + org_repos.error)
                continue
            for r in org_repos:
                scan_repos.append(r.full_name)
        else:
            scan_repos.append(line)

    # Deduplicate
    scan_repos = list(dict.fromkeys(scan_repos))

    # Spawn scanner coglet for each repo
    for repo in scan_repos:
        is_self = repo == SOURCE_REPO
        run = coglet_runtime.run(scanner, procs, capability_overrides=worker_caps)
        run.process().send({"repo": repo, "is_self_repo": is_self})

    # Mark today as scanned
    data.get("github/last_scan.txt").write(today)
    print("github: dispatched " + str(len(scan_repos)) + " scans")

else:
    print(f"github: unknown channel {channel!r}")
```

**Step 2: Commit**

```bash
git add images/cogent-v1/apps/github/main.py
git commit -m "feat(github): add github cog orchestrator"
```

---

### Task 8: Register channels in init.py

**Files:**
- Modify: `images/cogent-v1/cogos/init.py`

**Step 1: Add `github:discover` to the pre-created channels list**

In `images/cogent-v1/cogos/init.py`, add `"github:discover"` to the channels list around line 95-101:

```python
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "discord-cog:review",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
    "io:web:request",
    "github:discover",
]:
    channels.create(ch_name)
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/init.py
git commit -m "feat(github): register github:discover channel in init"
```

---

### Task 9: Verify cog manifest generation

**Step 1: Check that the cog manifest builder picks up `apps/github/`**

The manifest builder should automatically discover `apps/github/cog.py` and its coglets. Verify by checking the build process:

```bash
grep -r "apps/" images/cogent-v1/init/ --include="*.py" | head -20
```

Look at how the image builder scans for cog directories. If it auto-discovers directories with `cog.py`, no changes needed. If it uses a hardcoded list, add `github` to it.

**Step 2: Run any existing tests**

```bash
python -m pytest tests/ -k "cog" -v --no-header 2>&1 | head -40
```

**Step 3: Commit any fixes**

```bash
git add -A && git commit -m "fix(github): ensure github cog is included in manifest build"
```

---

### Task 10: End-to-end verification

**Step 1: Verify file structure**

```bash
find images/cogent-v1/apps/github -type f | sort
```

Expected:
```
images/cogent-v1/apps/github/cog.py
images/cogent-v1/apps/github/discovery/cog.py
images/cogent-v1/apps/github/discovery/main.md
images/cogent-v1/apps/github/main.py
images/cogent-v1/apps/github/scanner/cog.py
images/cogent-v1/apps/github/scanner/main.md
```

**Step 2: Verify static files**

```bash
cat images/cogent-v1/whoami/source_repo.md
cat images/cogent-v1/files/data/github/repos.md
```

**Step 3: Verify GitHub capability has list_org_repos**

```bash
grep "list_org_repos" src/cogos/capabilities/github_cap.py
```

**Step 4: Verify init.py has github:discover channel**

```bash
grep "github:discover" images/cogent-v1/cogos/init.py
```

**Step 5: Final commit if any cleanup needed**

```bash
git add -A && git commit -m "feat(github): github awareness cog — complete implementation"
```
