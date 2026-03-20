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

## Step 2: Get GitHub commits via capability

```python
repos_to_check = ["metta-ai/metta", "metta-ai/cogos", "metta-ai/cogents-v1"]
all_commits = {}
for rp in repos_to_check:
    owner, name = rp.split("/")
    info = github.get_repo(owner, name)
    if hasattr(info, 'error'):
        print(f"{rp}: {info.error}")
        all_commits[name] = []
    else:
        contribs = github.list_contributions(owner, limit=100)
        if hasattr(contribs, 'error'):
            print(f"{rp} contributions: {contribs.error}")
            all_commits[name] = []
        else:
            all_commits[name] = [{"author": c.repo.split("/")[-1] if "/" in c.repo else c.repo, "type": c.type, "date": c.date} for c in contribs]
            print(f"{name}: {len(all_commits[name])} events")
```

Actually, `list_contributions` takes a username not owner. Let me use a different approach. Search for what github methods exist first.

## Step 2 (revised): Search github capability

Run this:
```python
print(dir(github))
print(github)
```

Then based on the output, figure out how to get recent commits. If the github
capability doesn't support listing commits directly, that's ok — just note it
and move on.

## Step 3: Build the report from Asana data

Even without commit data, build a report showing the sprint threads and their
assignees. Use whatever GitHub data you managed to get.

Build two views per the brief:
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

```python
raw = secrets.get("cogent/{cogent}/discord_channel_id")
channel_id = raw.value
thread = discord.create_thread(channel_id, f"Standup — {today}")
if hasattr(thread, 'error'):
    print(f"Thread error: {thread.error}")
    discord.send(channel_id, report)
else:
    discord.send(thread.id, report)
print("Posted to Discord")
```
