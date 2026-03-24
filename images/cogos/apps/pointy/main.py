# Pointy — Python Orchestrator
# Routes channel events, fetches data (no LLM), spawns LLM coglets for synthesis.
# Uses procs.spawn() directly instead of cog_registry + coglet_runtime.

import datetime

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# ── Config ──────────────────────────────────────────────────────
PROJECT_ID = "1213471594342425"
WORKSPACE_ID = "1209016784099267"
FOLDER_ID = "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq"
DISCORD_CHANNEL = "1483962779336446114"
REPOS = [("Metta-AI", "metta"), ("Metta-AI", "cogos"), ("Metta-AI", "cogents-v1")]

# Load team mappings from secrets (Asana display name -> GitHub login)
try:
    _team_raw = secrets.get("cogent/{cogent}/pointy_team_mappings")
    TEAM = json.loads(_team_raw.value if hasattr(_team_raw, "value") else _team_raw)
except Exception as _e:
    print("WARN: could not load team mappings from secrets: " + str(_e))
    TEAM = {}


# ── Helpers ─────────────────────────────────────────────────────

def fetch_threads():
    """Fetch active threads from current month's Asana section."""
    sections = asana.list_sections(PROJECT_ID)
    if hasattr(sections, "error"):
        print("ERROR fetching sections: " + str(sections.error))
        return []

    now = datetime.datetime.now(datetime.timezone.utc)
    month_name = now.strftime("%B")
    year = now.strftime("%Y")
    target_section = None
    for s in sections:
        if month_name in s["name"] and year in s["name"]:
            target_section = s
            break
    if not target_section and sections:
        target_section = sections[-1]
    print("Section: " + str(target_section))

    tasks = asana.list_tasks(PROJECT_ID, limit=100)
    if hasattr(tasks, "error"):
        print("ERROR fetching tasks: " + str(tasks.error))
        return []

    threads = []
    for t in tasks:
        detail = asana.get_task(t.id)
        if hasattr(detail, "error") or not detail.name.strip():
            continue
        if detail.completed:
            continue
        if target_section and detail.section and target_section["name"] not in detail.section:
            continue
        github_login = TEAM.get(detail.assignee, "")
        threads.append({
            "name": detail.name,
            "assignee": detail.assignee,
            "github": github_login,
            "notes": detail.notes[:500] if detail.notes else "",
            "custom_fields": detail.custom_fields,
            "id": detail.id,
            "stage": detail.custom_fields.get("Stage", ""),
            "phase": detail.custom_fields.get("Phase", ""),
            "status": detail.custom_fields.get("Status", ""),
            "priority": detail.custom_fields.get("Priority", ""),
        })
    print("Fetched " + str(len(threads)) + " active threads")
    return threads


def fetch_reporting_window():
    """Find previous report to determine SINCE timestamp."""
    recent = google_docs.list_files(FOLDER_ID, order_by="createdTime desc", limit=1)
    now = datetime.datetime.now(datetime.timezone.utc)
    if hasattr(recent, "error") or not recent:
        since = (now - datetime.timedelta(days=14)).isoformat()
    else:
        since = recent[0].created_time
    return since, now.isoformat()


def fetch_github_activity(threads, since):
    """Fetch PRs and commits from the 3 main repos for all thread owners."""
    since_dt = datetime.datetime.fromisoformat(since.replace("Z", "+00:00"))
    github_users = set(t["github"] for t in threads if t["github"])

    # PRs per repo (3 calls total)
    all_prs = {}
    for owner, repo in REPOS:
        prs = github.list_pull_requests(owner, repo, state="closed", limit=30)
        if not hasattr(prs, "error"):
            repo_prs = []
            for p in prs:
                repo_prs.append({
                    "number": p.number, "title": p.title,
                    "user": getattr(p, "user", ""),
                    "merged_at": getattr(p, "merged_at", ""),
                    "url": getattr(p, "html_url", getattr(p, "url", "")),
                })
            all_prs[repo] = repo_prs
            print("  " + repo + ": " + str(len(repo_prs)) + " closed PRs")

    # Commits per user per repo
    all_commits = {}
    for gl in sorted(github_users):
        user_commits = {}
        for owner, repo in REPOS:
            commits = github.list_commits(owner, repo, author=gl, since=since_dt, limit=20)
            if not hasattr(commits, "error") and commits:
                user_commits[repo] = [{
                    "sha": c.sha[:7], "message": c.message[:120], "date": c.date,
                } for c in commits]
        if user_commits:
            all_commits[gl] = user_commits
            total = sum(len(v) for v in user_commits.values())
            print("  " + gl + ": " + str(total) + " commits")

    return all_prs, all_commits


def spawn_coglet(name, prompt_key):
    """Spawn an LLM coglet by reading its prompt from the file store."""
    content = src.get(prompt_key).read()
    if hasattr(content, "content"):
        content = content.content
    if not content:
        print("ERROR: no content for coglet at " + prompt_key)
        return None
    caps = {
        "asana": None, "github": None, "google_docs": None,
        "discord": None, "channels": None, "secrets": None,
        "file": None, "disk": disk,
    }
    return procs.spawn(
        name=name,
        content=content,
        mode="one_shot",
        executor="llm",
        capabilities=caps,
    )


# ── Channel routing ─────────────────────────────────────────────

if channel == "pointy:daily-tick":
    print("=== Daily Thread Update ===")

    # Phase 1: Fetch all data (Python, no LLM)
    threads = fetch_threads()
    since, until = fetch_reporting_window()
    print("Window: " + since + " to " + until)
    all_prs, all_commits = fetch_github_activity(threads, since)

    # Build summary for the LLM
    thread_summaries = []
    for t in threads:
        gl = t["github"]
        commits = sum(len(v) for v in all_commits.get(gl, {}).values())
        user_prs = []
        for repo, prs in all_prs.items():
            for p in prs:
                if p["user"] == gl and p["merged_at"]:
                    user_prs.append(repo + "#" + str(p["number"]) + " " + p["title"])
        commit_msgs = []
        if gl in all_commits:
            for repo, repo_commits in all_commits[gl].items():
                for c in repo_commits[:5]:
                    commit_msgs.append(repo + " " + c["sha"] + " " + c["message"])
        thread_summaries.append({
            "name": t["name"], "assignee": t["assignee"],
            "github": gl, "stage": t["stage"], "phase": t["phase"],
            "status": t["status"], "priority": t["priority"],
            "notes": t["notes"], "id": t["id"],
            "commit_count": commits,
            "pr_titles": user_prs[:10],
            "commit_messages": commit_msgs[:10],
        })

    # Write data to file store for the coglet
    data_payload = {
        "since": since, "until": until,
        "threads": thread_summaries,
        "thread_count": len(threads),
    }
    disk.get("daily-data.json").write(json.dumps(data_payload, indent=2, default=str))
    print("Data written. Spawning daily coglet...")

    # Phase 2: Spawn LLM coglet for synthesis
    handle = spawn_coglet("pointy/daily", "daily-coglet.md")
    if handle:
        handle.send({"action": "synthesize", "data_key": "daily-data.json"})
        print("Daily coglet spawned: " + str(handle))

elif channel == "pointy:pitch-requested":
    print("=== Pitch Review ===")
    handle = spawn_coglet("pointy/pitch", "pitch-instructions.md")
    if handle:
        handle.send(payload)

elif channel == "pointy:feedback-requested":
    print("=== Feedback Processing ===")
    handle = spawn_coglet("pointy/feedback", "feedback-coglet.md")
    if handle:
        handle.send(payload)

elif channel == "pointy:followup-requested":
    print("=== Pitch Follow-Up ===")
    handle = spawn_coglet("pointy/followup", "followup-coglet.md")
    if handle:
        handle.send(payload)

else:
    print("pointy: unknown channel " + channel)
