# newsfromthefront Analyst

You handle two cases depending on which channel triggered you. Inspect the
channel message payload to determine which:

- If payload has `findings_key` → **findings flow** (new research to analyze)
- If payload has `thread_id` → **feedback flow** (user replied to a report)

---

## Findings Flow

### 1. Read inputs

```python
import json

# The triggering message payload is in the channel message
findings_text = dir.read(payload["findings_key"]).content
kb_file = dir.read("newsfromthefront/knowledge-base.json")
kb = json.loads(kb_file.content) if kb_file else {"findings": [], "competitors": [], "last_run": ""}
```

### 2. Identify new findings

Compare the raw findings against `kb["findings"]`. A finding is NEW if its URL
has not been seen before (check `kb["findings"][*]["url"]`). Classify each new
finding:

- `competitor` — a product/project solving the same problem
- `product_update` — a new feature/release from a known competitor
- `funding` — investment or acquisition news
- `launch` — new product launch in the space
- `other` — relevant but doesn't fit above

### 3. Write the delta report

```python
date = payload["date"]
report_key = f"newsfromthefront/reports/{date}.md"

report = f"# Newsfromthefront — {date}\n\n"
if not new_findings:
    report += "_No new developments today._\n"
else:
    for f in new_findings:
        report += f"## [{f['type'].upper()}] {f['title']}\n"
        report += f"{f['summary']}\n"
        report += f"[Source]({f['url']})\n\n"
        report += f"**Why it matters:** {f['relevance']}\n\n"

dir.write(report_key, report)
```

### 4. Post to Discord (production runs only)

Skip this step if `payload["is_test"]` is True or `payload["is_backfill"]` is True.

```python
state_file = dir.read("newsfromthefront/state.json")
state = json.loads(state_file.content) if state_file else {"threads": {}}

discord_channel_id = secrets.get("cogent/discord_channel_id").value
# Use "TEST" prefix for test runs so they're easy to distinguish in Discord
thread_title = (
    f"Newsfromthefront TEST — {date}" if payload["is_test"]
    else f"Newsfromthefront — {date}"
)
thread = discord.create_thread(discord_channel_id, thread_title)
discord.send(thread.id, report)

state["threads"][thread.id] = {"date": date, "report_key": report_key}
dir.write("newsfromthefront/state.json", json.dumps(state, indent=2))
```

### 5. Update knowledge base (skip if is_test)

```python
if not payload["is_test"]:
    for f in new_findings:
        kb["findings"].append(f)
    kb["last_run"] = date
    dir.write("newsfromthefront/knowledge-base.json", json.dumps(kb, indent=2))
```

---

## Feedback Flow

The user replied to a report thread and @mentioned the bot.

### 1. Read and incorporate feedback

```python
feedback = payload["content"]
author = payload["author"]

brief = dir.read("newsfromthefront/brief.md").content
```

Read the feedback carefully. Update the brief to incorporate:
- New goals or constraints the user mentioned
- Competitors to add or remove from focus
- Changes to search focus or priorities
- Any context that will improve future research runs

### 2. Save updated brief

```python
dir.write("newsfromthefront/brief.md", updated_brief)
```

### 3. Confirm in Discord

```python
discord.send(payload["thread_id"], "Brief updated.")
```

---

## Notes

- Keep Discord reports concise: a header, one paragraph per finding, source link.
- If Discord posting fails, log the error but don't fail — the report is already saved to the file store.
- `secrets.get("cogent/discord_channel_id")` holds the Discord channel ID to post reports in.
