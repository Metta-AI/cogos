# GitHub Repo Scanner

@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/files.md}

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
existing = data.get(repo + "/summary.md").read()
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
data.get(repo + "/summary.md").write(summary_content)
```

### 4. Append to recent_changes.md

Read the existing recent_changes.md. Compare the repo's current state (from README, description, topics) with what's in the existing summary to identify what changed.

Append a dated entry:

```python
today = stdlib.time.strftime("%Y-%m-%d")
entry = "\n## " + today + "\n" + changes_summary + "\n"

existing_changes = data.get(repo + "/recent_changes.md").read()
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

data.get(repo + "/recent_changes.md").write(content)
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
