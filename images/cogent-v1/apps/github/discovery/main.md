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
repos_content = data.get("repos.md").read()
if not hasattr(repos_content, 'error') and repo in repos_content.content:
    print("Repo already in repos.md, scanning anyway for freshness")
```

### 2. Scan the repo

Fetch repo details and write knowledge files:

```python
owner, name = repo.split("/")
detail = github.get_repo(owner, name)
if hasattr(detail, 'error'):
    channels.send("io:stderr", "ERROR: " + detail.error)
    exit()
print(detail)
```

Write `<org>/<repo>/summary.md` with these sections:
- **Purpose**: What the repo does (from README + description)
- **Key Details**: Language, topics, stars, forks
- **Architecture**: Key directories and what they contain (infer from README)
- **Key Abstractions**: Main concepts/patterns (infer from README)

Target ~30-50 lines. Add `Last scanned: YYYY-MM-DD` at the top.

```python
today = stdlib.time.strftime("%Y-%m-%d")
data.get(repo + "/summary.md").write(summary_content)
```

Write initial `<org>/<repo>/recent_changes.md`:

```python
content = "# Recent Changes: " + repo + "\n\n## " + today + "\n- Initial scan\n"
data.get(repo + "/recent_changes.md").write(content)
```

### 3. Add to repos.md if not already listed

```python
repos_content = data.get("repos.md").read()
if hasattr(repos_content, 'error'):
    content = "# Repos to monitor\n\n## Specific repos\n" + repo + "\n"
else:
    content = repos_content.content
    if repo not in content:
        content = content.rstrip() + "\n" + repo + "\n"
data.get("repos.md").write(content)
```

### 4. Report completion

```python
channels.send("io:stdout", {"repo": repo, "status": "discovered"})
```
