# Daily Thread Update Instructions

Cross-reference the Asana Thread Roadmap with GitHub engineering activity to produce
a business-readable report showing how each thread's goals are progressing.

**IMPORTANT: Minimize run_code calls.** Each tool turn costs tokens. Batch all data
fetching into ONE run_code call, then reason about the data, then publish in ONE
run_code call. Target 3-4 run_code calls total, not 10+.

## Step 1: Fetch ALL data in a single run_code call

Execute this as ONE run_code block. It fetches Asana threads, maps owners, determines
the reporting window, and gathers GitHub activity — all in one call.

```python
import datetime, json

PROJECT_ID = "1213471594342425"
FOLDER_ID = "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq"
REPOS = [("Metta-AI", "metta"), ("Metta-AI", "cogos"), ("Metta-AI", "cogents-v1")]

# Team mappings from brief
TEAM = {
    "Alex Smith": "sasmith", "Subhojeet Pramanik": "subho406",
    "Richard Higgins": "relh", "Malcolm Ocean": "malcolmocean",
    "Andre von Houck": "treeform", "Noah Farr": "noahfarr",
    "Alexandros Vardakostas": "Al-does", "Martin Hess": "marty-spec",
    "Nishad Singh": "nishu-builder", "David Bloomin": "daveey",
    "Yatharth Agarwal": "yatharth",
}

# ── 1a: Find current month's section ──
sections = asana.list_sections(PROJECT_ID)
now = datetime.datetime.now(datetime.timezone.utc)
month_name, year = now.strftime("%B"), now.strftime("%Y")
target_section = None
if not hasattr(sections, 'error'):
    for s in sections:
        if month_name in s["name"] and year in s["name"]:
            target_section = s
            break
    if not target_section and sections:
        target_section = sections[-1]
print(f"Section: {target_section}")

# ── 1b: Fetch threads with details (skip completed, skip comments for speed) ──
tasks = asana.list_tasks(PROJECT_ID, limit=100)
threads = []
if not hasattr(tasks, 'error'):
    for t in tasks:
        detail = asana.get_task(t.id)
        if hasattr(detail, 'error') or not detail.name.strip():
            continue
        if detail.completed:
            continue
        if target_section and detail.section and target_section["name"] not in detail.section:
            continue
        github_login = TEAM.get(detail.assignee, "")
        threads.append({
            "name": detail.name, "assignee": detail.assignee,
            "github": github_login, "notes": detail.notes[:400],
            "custom_fields": detail.custom_fields,
            "id": detail.id, "completed": detail.completed,
        })
print(f"Threads: {len(threads)}")
# NOTE: Comments are skipped for speed. If you need comment context for a
# specific thread, fetch with asana.get_stories_for_task(thread_id) in Step 2.

# ── 1c: Reporting window ──
recent = google_docs.list_files(FOLDER_ID, order_by="createdTime desc", limit=1)
if hasattr(recent, 'error') or not recent:
    since = (now - datetime.timedelta(days=14)).isoformat()
else:
    since = recent[0].created_time
since_dt = datetime.datetime.fromisoformat(since.replace("Z", "+00:00"))
print(f"Since: {since}")

# ── 1d: GitHub activity (3 repos, per-user commits + per-repo PRs) ──
github_users = set(t["github"] for t in threads if t["github"])
all_prs = {}
for owner, repo in REPOS:
    prs = github.list_pull_requests(owner, repo, state="closed", limit=30)
    if not hasattr(prs, 'error'):
        all_prs[repo] = [{"number": p.number, "title": p.title, "user": getattr(p, 'user', ''),
                          "merged_at": getattr(p, 'merged_at', ''), "url": getattr(p, 'html_url', getattr(p, 'url', ''))}
                         for p in prs]

all_commits = {}
for gl in sorted(github_users):
    uc = {}
    for owner, repo in REPOS:
        commits = github.list_commits(owner, repo, author=gl, since=since_dt, limit=20)
        if not hasattr(commits, 'error') and commits:
            uc[repo] = [{"sha": c.sha[:7], "message": c.message[:100], "date": c.date} for c in commits]
    if uc:
        all_commits[gl] = uc

# Print summary
for t in threads:
    gl = t["github"]
    commits = sum(len(v) for v in all_commits.get(gl, {}).values())
    prs_count = sum(1 for repo_prs in all_prs.values() for p in repo_prs if p["user"] == gl)
    stage = t["custom_fields"].get("Stage", "")
    status = t["custom_fields"].get("Status", "")
    print(f"  {t['name'][:40]:40s} | {t['assignee']:20s} | @{gl:15s} | {stage:10s} | {status:10s} | {commits}c {prs_count}pr")
```

## Step 2: Correlate and synthesize (LLM reasoning — no run_code needed)

Using the data printed above, write the report. For each thread:

- **Direct attribution**: PRs and commits by the thread's owner default to that thread.
- **Cross-thread**: If an owner has work clearly related to a different thread, note it.
- **No visible activity**: Say so plainly — thread goes in Dormant section.
- Weave in Asana comment context (blockers, scope changes, decisions).

Report structure:
```
# Daily Thread Update -- YYYY-MM-DD
**Period:** SINCE to NOW
**Threads:** N this month | M with activity | K dormant

## Key Observations
- [3-6 bullet points: cross-cutting themes, accomplishments, risks]

### THREAD_NAME
**Owner:** NAME (@github)
**Stage:** X | **Phase:** Y | **Status:** Z | **Priority:** P
**Goal:** 1-2 sentence summary from Asana notes

Since the last report, [narrative of what moved toward the goal].

Overall, [1-3 factual sentences on trajectory].

## Dormant Threads
- THREAD_NAME (Owner) — STAGE, STATUS
```

Sort active threads by activity volume. Write the FULL report text, then proceed to Step 3.

## Step 3: Publish in a single run_code call

Save the report text to a variable, create the Google Doc, insert the text, apply
formatting, and post to Discord — all in ONE run_code call.

```python
import datetime
today = datetime.date.today().isoformat()
report_text = """PASTE THE FULL REPORT TEXT HERE"""

# Create doc
doc = google_docs.create_doc(f"Daily Thread Update — {today}", "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq")
if hasattr(doc, 'error'):
    print(f"ERROR creating doc: {doc.error}")
else:
    # Insert text at index 1
    requests = [{"insertText": {"location": {"index": 1}, "text": report_text}}]
    # Apply heading styles after insertion
    # Calculate line offsets and add updateParagraphStyle requests for HEADING_1, HEADING_2
    result = google_docs.batch_update(doc.id, requests)
    print(f"Published: {doc.url}")
    # Notify Discord
    discord.send("1483962779336446114", f"Daily Thread Update ready: {doc.url}")
```
