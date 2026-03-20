@{mnt/boot/standup/brief.md}

# Instructions

You MUST execute the following code blocks in order using `run_code`. Do NOT
skip any step. Do NOT use sample or fake data. Each block depends on the previous.

## Step 1: Get Asana tasks

```python
project_id = "1213471594342425"
tasks = asana.list_tasks(project_id, limit=100)
threads = []
if hasattr(tasks, 'error'):
    print("ERROR: " + str(tasks.error))
else:
    for t in tasks:
        d = asana.get_task(t.id)
        if not hasattr(d, 'error') and d.name.strip():
            if d.section and "March" in d.section and "2026" in d.section:
                threads.append({"name": d.name, "assignee": d.assignee})
    print(f"Found {len(threads)} threads")
    for t in threads:
        print(f"  {t['name']} -> {t['assignee']}")
```

## Step 2: Discover GitHub capability

The `github` capability doesn't have a `list_commits` method yet. Search for
what's available and use what you can:

```python
print(github)
```

Use `github.get_repo(owner, name)` to verify access to each repo. If there's
no way to get recent commits, skip this step — the report will be Asana-only.

## Step 3: Build the report from Asana data

Build a report showing sprint threads and assignees. Use whatever GitHub data
you managed to get. Build two views per the brief:
- By Thread: each thread, who's assigned
- By Person: each person, their threads

## Step 4: Save

```python
import datetime
today = datetime.date.today().isoformat()
disk.get(f"reports/{today}.md").write(report)
print("Saved report")
```

## Step 5: Post to Discord

Use the channel ID from the brief directly:

```python
channel_id = "1483962779336446114"
thread = discord.create_thread(channel_id, f"Standup — {today}")
if hasattr(thread, 'error'):
    print(f"Thread error: {thread.error}")
    discord.send(channel_id, report)
else:
    discord.send(thread.id, report)
print("Posted to Discord")
```
