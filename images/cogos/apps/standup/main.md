@{mnt/boot/standup/brief.md}

# Instructions

You MUST execute the following code blocks in order using `run_code`. Do NOT
skip any step. Do NOT use sample or fake data. Each block depends on the previous.

## Step 1: Get Asana sprint threads

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

## Step 2: Get GitHub commits from last 24 hours

```python
import datetime
since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
repos = [("metta-ai", "metta"), ("metta-ai", "cogos"), ("metta-ai", "cogents-v1")]
all_commits = {}
for owner, name in repos:
    result = github.list_commits(owner, name, since=since, limit=100)
    if hasattr(result, 'error'):
        print(f"{name}: {result.error}")
        all_commits[name] = []
    else:
        all_commits[name] = [{"sha": c.sha, "msg": c.message, "author": c.author, "date": c.date} for c in result]
        print(f"{name}: {len(all_commits[name])} commits")
        for c in all_commits[name][:5]:
            print(f"  {c['sha'][:7]} {c['author']}: {c['msg'][:60]}")
```

## Step 3: Match commits to threads, build report, save, and post

For each commit, judge which Asana thread it relates to by comparing the commit
message topic to thread names. Rules:
- CI/merge commits ("ci: update", "Merge branch") go to "Untracked"
- A commit can match at most one thread
- If unclear, put in "Untracked"
- Use the commit author field as the person name

Build a dict: `matches[thread_name][person][repo_name] = count`

Then render two views and save. You MUST do all of this in a SINGLE run_code call:

```python
import datetime
from collections import defaultdict

# -- Build matches dict --
# YOU fill in the matching logic here. For each commit in all_commits,
# decide which thread it belongs to based on message content vs thread names.
# Store in: matches[thread_name][author][repo_name] += 1
# Unmatched commits go under matches["Untracked"][author][repo_name] += 1

matches = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

# ... your matching logic here ...

# -- Render report --
today = datetime.date.today().isoformat()
lines = [f"# Daily Standup — {today}", ""]

# View 1: By Thread
lines.append("## By Thread")
lines.append("")
total_matched = 0
total_untracked = 0
for thread_name in sorted(matches.keys()):
    if thread_name == "Untracked":
        continue
    people = matches[thread_name]
    lines.append(f"### {thread_name}")
    for person in sorted(people.keys()):
        repos_str = ", ".join(f"{r} ({c})" for r, c in sorted(people[person].items()) if c > 0)
        if repos_str:
            lines.append(f"- {person}: {repos_str}")
            total_matched += sum(people[person].values())
    lines.append("")

if "Untracked" in matches:
    lines.append("### Untracked")
    for person in sorted(matches["Untracked"].keys()):
        repos_str = ", ".join(f"{r} ({c})" for r, c in sorted(matches["Untracked"][person].items()) if c > 0)
        if repos_str:
            lines.append(f"- {person}: {repos_str}")
            total_untracked += sum(matches["Untracked"][person].values())
    lines.append("")

# View 2: By Person
lines.append("## By Person")
lines.append("")
all_people = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
for thread_name, people in matches.items():
    for person, repos in people.items():
        for repo_name, count in repos.items():
            all_people[person][thread_name][repo_name] += count

for person in sorted(all_people.keys()):
    lines.append(f"### {person}")
    for thread_name in sorted(all_people[person].keys()):
        repos_str = ", ".join(f"{r} ({c})" for r, c in sorted(all_people[person][thread_name].items()) if c > 0)
        if repos_str:
            lines.append(f"- {thread_name}: {repos_str}")
    lines.append("")

total = total_matched + total_untracked
num_repos = len([r for r in all_commits if all_commits[r]])
lines.append("---")
lines.append(f"{total} commits across {num_repos} repos | {total_matched} matched, {total_untracked} untracked")

report = "\n".join(lines)

# -- Save --
disk.get(f"reports/{today}.md").write(report)
print("Saved report")
print(report)

# -- Post to Discord --
channel_id = "1483962779336446114"
thread = discord.create_thread(channel_id, f"Standup — {today}")
if hasattr(thread, 'error'):
    discord.send(channel_id, report)
else:
    discord.send(thread.id, report)
print("Posted to Discord")
```
