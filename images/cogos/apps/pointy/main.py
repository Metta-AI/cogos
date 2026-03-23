# Pointy — Python Orchestrator
# Routes channel events, fetches data (no LLM), spawns LLM coglets for synthesis.

import datetime

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# ── Config ──────────────────────────────────────────────────────
PROJECT_ID = "1213471594342425"
WORKSPACE_ID = "1209016784099267"
FOLDER_ID = "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq"
DISCORD_CHANNEL = "1483962779336446114"
REPOS = [("Metta-AI", "metta"), ("Metta-AI", "cogos"), ("Metta-AI", "cogents-v1")]
TEAM = {
    "Alex Smith": "sasmith", "Subhojeet Pramanik": "subho406",
    "Richard Higgins": "relh", "Malcolm Ocean": "malcolmocean",
    "Andre von Houck": "treeform", "Noah Farr": "noahfarr",
    "Alexandros Vardakostas": "Al-does", "Martin Hess": "marty-spec",
    "Nishad Singh": "nishu-builder", "David Bloomin": "daveey",
    "Yatharth Agarwal": "yatharth",
}

# ── Coglet definitions ──────────────────────────────────────────
daily_coglet = cog.make_coglet("daily", entrypoint="main.md",
    files={"main.md": src.get("daily-coglet.md").read().content})
pitch_coglet = cog.make_coglet("pitch", entrypoint="main.md",
    files={"main.md": src.get("pitch-instructions.md").read().content})
feedback_coglet = cog.make_coglet("feedback", entrypoint="main.md",
    files={"main.md": src.get("feedback-coglet.md").read().content})
followup_coglet = cog.make_coglet("followup", entrypoint="main.md",
    files={"main.md": src.get("followup-coglet.md").read().content})

coglet_caps = {
    "asana": None, "github": None, "google_docs": None,
    "discord": None, "channels": None, "secrets": None,
    "disk": disk,
}


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
                    "additions": getattr(p, "additions", 0),
                    "deletions": getattr(p, "deletions", 0),
                })
            all_prs[repo] = repo_prs
            print("  " + repo + ": " + str(len(repo_prs)) + " closed PRs")

    # Commits per user per repo (up to 33 calls: 11 users x 3 repos)
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


def publish_to_google_docs(report_text, date_str):
    """Create a Google Doc, insert text, apply basic formatting, notify Discord."""
    doc = google_docs.create_doc("Daily Thread Update \u2014 " + date_str, FOLDER_ID)
    if hasattr(doc, "error"):
        print("ERROR creating doc: " + str(doc.error))
        return None

    # Insert text
    requests = [{"insertText": {"location": {"index": 1}, "text": report_text}}]
    result = google_docs.batch_update(doc.id, requests)
    if hasattr(result, "error"):
        print("ERROR inserting text: " + str(result.error))
    else:
        print("Inserted text into doc")

    # Apply heading styles
    fmt_requests = []
    lines = report_text.split("\n")
    idx = 1  # doc starts at index 1
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if line.startswith("# ") and not line.startswith("## "):
            fmt_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": idx + line_len},
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "fields": "namedStyleType",
                }
            })
        elif line.startswith("## "):
            fmt_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": idx + line_len},
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    "fields": "namedStyleType",
                }
            })
        elif line.startswith("### "):
            fmt_requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": idx, "endIndex": idx + line_len},
                    "paragraphStyle": {"namedStyleType": "HEADING_3"},
                    "fields": "namedStyleType",
                }
            })
        idx += line_len

    if fmt_requests:
        fmt_result = google_docs.batch_update(doc.id, fmt_requests)
        if not hasattr(fmt_result, "error"):
            print("Applied " + str(len(fmt_requests)) + " heading styles")

    # Notify Discord
    discord.send(DISCORD_CHANNEL, "Daily Thread Update ready: " + doc.url)
    print("Published: " + doc.url)
    return doc


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
        thread_summaries.append({
            "name": t["name"],
            "assignee": t["assignee"],
            "github": gl,
            "stage": t["stage"],
            "phase": t["phase"],
            "status": t["status"],
            "priority": t["priority"],
            "notes": t["notes"],
            "id": t["id"],
            "commit_count": commits,
            "pr_titles": user_prs[:10],
            "commit_messages": [],
        })
        # Add commit messages for context
        if gl in all_commits:
            msgs = []
            for repo, repo_commits in all_commits[gl].items():
                for c in repo_commits[:5]:
                    msgs.append(repo + " " + c["sha"] + " " + c["message"])
            thread_summaries[-1]["commit_messages"] = msgs[:10]

    # Write data to file store for the coglet
    data_payload = {
        "since": since,
        "until": until,
        "threads": thread_summaries,
        "thread_count": len(threads),
    }
    disk.get("daily-data.json").write(json.dumps(data_payload, indent=2, default=str))
    print("Data written to disk. Spawning daily coglet...")

    # Phase 2: Spawn LLM coglet for synthesis
    run = coglet_runtime.run(daily_coglet, procs, capability_overrides=coglet_caps)
    run.process().send({"action": "synthesize", "data_key": "daily-data.json"})

elif channel == "pointy:pitch-requested":
    print("=== Pitch Review ===")
    run = coglet_runtime.run(pitch_coglet, procs, capability_overrides=coglet_caps)
    run.process().send(payload)

elif channel == "pointy:feedback-requested":
    print("=== Feedback Processing ===")
    run = coglet_runtime.run(feedback_coglet, procs, capability_overrides=coglet_caps)
    run.process().send(payload)

elif channel == "pointy:followup-requested":
    print("=== Pitch Follow-Up ===")
    run = coglet_runtime.run(followup_coglet, procs, capability_overrides=coglet_caps)
    run.process().send(payload)

else:
    print("pointy: unknown channel " + channel)
