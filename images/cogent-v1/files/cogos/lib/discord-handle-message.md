# discord-handle-message

You received a Discord message. The channel message payload tells you who sent
it and what they said. Check the payload fields to decide how to respond.

## Routing logic

### 1. Check for newsfromthefront thread replies

```python
import json

state_file = dir.read("newsfromthefront/state.json")
state = json.loads(state_file.content) if state_file else {"threads": {}}
known_threads = state.get("threads", {})

# payload fields from io:discord:mention include channel_id (thread ID if in a thread)
thread_id = payload.get("channel_id", "")

if thread_id and thread_id in known_threads:
    # This is a reply to a newsfromthefront report thread — route as feedback
    channels.send("newsfromthefront:discord-feedback", {
        "thread_id": thread_id,
        "content": payload["content"],
        "author": payload["author"],
    })
    exit()
```

### 2. Check for newsfromthefront commands

```python
content = payload.get("content", "").strip().lower()

if content == "test" or content.startswith("test "):
    channels.send("newsfromthefront:run-requested", {
        "mode": "test",
        "after_date": "",
        "before_date": "",
    })
    discord.send(payload["channel_id"], "Starting test run — results will appear in a new thread.")
    exit()

if content.startswith("backfill "):
    parts = content.split()
    if len(parts) == 3:
        after_date, before_date = parts[1], parts[2]
        channels.send("newsfromthefront:run-requested", {
            "mode": "backfill",
            "after_date": after_date,
            "before_date": before_date,
        })
        discord.send(payload["channel_id"], f"Starting backfill {after_date} → {before_date}.")
        exit()
```

### 3. Normal chat response

For all other messages, respond helpfully:

- For DMs (`payload["dm"] == true`): use `discord.dm(user_id=payload["author_id"], content=your_reply)`
- For mentions: use `discord.send(channel=payload["channel_id"], content=your_reply)`

Be helpful, concise, and friendly. If you don't know something, say so.
