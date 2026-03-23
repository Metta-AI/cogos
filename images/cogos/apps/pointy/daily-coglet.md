@{mnt/boot/pointy/whoami/index.md}
@{mnt/boot/pointy/learnings.md}
@{mnt/boot/pointy/writing-style.md}

# Daily Thread Update — Synthesis & Publish

You are Pointy's daily report writer. The orchestrator has already fetched all data
from Asana and GitHub and written it to `disk`. Your job:

1. Read the pre-fetched data
2. Correlate GitHub activity to thread goals
3. Write a narrative report
4. Publish to Google Docs
5. Notify Discord

## Step 1: Read data

```python
import json
raw = disk.get("daily-data.json").read()
data = json.loads(raw.content if hasattr(raw, 'content') else raw)
since = data["since"]
until = data["until"]
threads = data["threads"]
print(f"Period: {since} to {until}")
print(f"Threads: {len(threads)}")
for t in threads:
    print(f"  {t['name'][:40]:40s} @{t['github']:15s} {t['stage']:10s} {t['commit_count']}c {len(t['pr_titles'])}pr")
```

## Step 2: Write the report

Using the data, write the full report. For each thread:

- **Active** (has commits or PRs): Write a narrative paragraph explaining what moved
  toward the thread's goal. Reference PRs by number only when they add context.
  Use commit messages to understand what was built.
- **Dormant** (no activity): List compactly at the bottom.

Report structure:
```
# Daily Thread Update — YYYY-MM-DD
**Period:** SINCE to UNTIL
**Threads:** N this month | M with activity | K dormant

## Key Observations
- [3-6 bullet points: themes, accomplishments, risks]

### THREAD_NAME
**Owner:** NAME (@github)
**Stage:** X | **Phase:** Y | **Status:** Z | **Priority:** P
**Goal:** 1-2 sentences from thread notes

Since the last report, [narrative of what moved toward the goal].

Overall, [1-3 factual sentences on trajectory].

## Dormant Threads
- THREAD_NAME (Owner) — STAGE, STATUS
```

## Step 3: Publish

Create the Google Doc, insert text, apply heading formatting, and notify Discord.
Do this in ONE run_code call:

```python
import datetime
today = datetime.date.today().isoformat()
FOLDER_ID = "1CDiEcCsr7M0vyzcYYBIidPBCU9kXymNq"
DISCORD_CHANNEL = "1483962779336446114"

report_text = """YOUR REPORT HERE"""

# Create doc
doc = google_docs.create_doc(f"Daily Thread Update — {today}", FOLDER_ID)
if hasattr(doc, 'error'):
    print(f"ERROR: {doc.error}")
else:
    # Insert text
    requests = [{"insertText": {"location": {"index": 1}, "text": report_text}}]
    google_docs.batch_update(doc.id, requests)

    # Apply heading styles
    fmt = []
    idx = 1
    for line in report_text.split("\n"):
        line_len = len(line) + 1
        style = None
        if line.startswith("# ") and not line.startswith("## "):
            style = "HEADING_1"
        elif line.startswith("## ") and not line.startswith("### "):
            style = "HEADING_2"
        elif line.startswith("### "):
            style = "HEADING_3"
        if style:
            fmt.append({"updateParagraphStyle": {
                "range": {"startIndex": idx, "endIndex": idx + line_len},
                "paragraphStyle": {"namedStyleType": style}, "fields": "namedStyleType"}})
        idx += line_len
    if fmt:
        google_docs.batch_update(doc.id, fmt)

    discord.send(DISCORD_CHANNEL, f"Daily Thread Update ready: {doc.url}")
    print(f"Published: {doc.url}")
```
