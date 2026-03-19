# newsfromthefront Backfill

@{mnt/boot/cogos/includes/memory/session.md}

You fill in the knowledge base with historical competitive intelligence, one
interval at a time. Each invocation processes a single interval then
re-triggers itself for the next one.

### 1. Check mode

```python
if payload["mode"] != "backfill":
    print("Not a backfill request — exiting.")
    exit()
```

### 2. Initialize or resume backfill state

```python
import json, datetime

state_file = dir.get("newsfromthefront/backfill-state.json").read()
if state_file and payload["after_date"] == "":
    # Resuming an in-progress backfill
    state = json.loads(state_file.content)
else:
    # Starting a new backfill
    after = payload["after_date"]
    before = payload["before_date"]
    after_dt = datetime.date.fromisoformat(after)
    before_dt = datetime.date.fromisoformat(before)
    # Week-by-week for ranges > 30 days, day-by-day otherwise
    delta_days = (before_dt - after_dt).days
    granularity = 7 if delta_days > 30 else 1
    state = {
        "after_date": after,
        "before_date": before,
        "current_date": after,
        "granularity_days": granularity,
        "intervals_done": 0,
        "findings_count": 0,
    }
    dir.get("newsfromthefront/backfill-state.json").write(json.dumps(state, indent=2))
```

### 3. Process the next interval

```python
import uuid

current = datetime.date.fromisoformat(state["current_date"])
interval_end = min(
    current + datetime.timedelta(days=state["granularity_days"]),
    datetime.date.fromisoformat(state["before_date"]),
)
interval_str = current.isoformat()

# Run searches for this interval using date range params
findings = []
brief = dir.get("newsfromthefront/brief.md").read().content

# Run Tavily, GitHub, Twitter searches with after_date/before_date
# (follow the same query generation logic as apps/newsfromthefront/researcher.md)
# ...

run_id = str(uuid.uuid4())
findings_key = f"newsfromthefront/findings/{interval_str}.md"
dir.get(findings_key).write(findings_content)
```

### 4. Advance state

After running analyst-style deduplication (compare findings against `knowledge-base.json`
by URL, keep only items whose URL has not been seen before):

```python
# Load KB and deduplicate
kb_file = dir.get("newsfromthefront/knowledge-base.json").read()
kb = json.loads(kb_file.content) if kb_file else {"findings": [], "competitors": [], "last_run": ""}
seen_urls = {f["url"] for f in kb["findings"]}
new_findings = [f for f in all_findings if f.get("url") not in seen_urls]

for f in new_findings:
    kb["findings"].append(f)
kb["last_run"] = interval_str
dir.get("newsfromthefront/knowledge-base.json").write(json.dumps(kb, indent=2))

state["current_date"] = interval_end.isoformat()
state["intervals_done"] += 1
state["findings_count"] += len(new_findings)
dir.get("newsfromthefront/backfill-state.json").write(json.dumps(state, indent=2))
```

### 5. Self-trigger or complete

```python
before_dt = datetime.date.fromisoformat(state["before_date"])
if interval_end < before_dt:
    # More intervals remain — re-trigger self
    channels.send("newsfromthefront:run-requested", {
        "mode": "backfill",
        "after_date": "",   # empty = resume from state file
        "before_date": "",
    })
    print(f"Backfill continuing — {state['intervals_done']} intervals done, next: {interval_end}")
else:
    # All done
    discord_channel_id = secrets.get("cogent/discord_channel_id").value
    discord.send(discord_channel_id,
        f"Backfill complete: {state['after_date']} → {state['before_date']}. "
        f"Knowledge base initialized with {state['findings_count']} findings."
    )
    # delete not supported in new API
    print("Backfill complete.")
```

## Notes

- Backfill is triggered by `@cogent backfill 2025-01-01 2025-03-01` in Discord.
- `discord-handle-message` parses the dates and sends to `newsfromthefront:run-requested`.
- A crash mid-backfill is safe — re-running with original dates is safe because KB deduplication
  will skip already-seen findings.
