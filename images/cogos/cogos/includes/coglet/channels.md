# Coglet Channels

Every coglet runs with five standard channels. These are the only way you communicate with the outside world — whether you're running locally or proxied to a remote cluster.

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `io:stdin` | **in** | Receives events/tasks that wake you or append to your running conversation |
| `io:stdout` | **out** | Primary output. May be schema-validated if the spawning cog declares an output schema |
| `io:stderr` | **out** | Errors, warnings, debug traces, progress notes (Unix stderr semantics) |
| `cog:from` | **in** | Messages from your parent cog — suggestions, requests, improvements. Injected into conversation context automatically |
| `cog:to` | **out** | Explicit updates sent to your parent cog — status reports, questions, results |

You don't need to know how these channels are implemented. Today they map to spawn channels; in the future they may be proxied across machines.

## io:stdin

Your input stream. Events arrive here from whatever system your cog has wired you to (Discord messages, HTTP requests, scheduled ticks, etc.).

**Wake-up behavior:** A new message on `io:stdin` wakes you if you're idle. If you're already running, it's appended to your conversation context as a new user message.

**Reading stdin:**
```python
# Messages arrive automatically — you don't need to poll.
# When woken, your latest stdin message is already in context.
# To read history:
msgs = channels.read("io:stdin", limit=10)
```

**What to expect:** The message format depends on what your cog wired you to. Check your task description for details. Common patterns:
- A plain text task description
- A JSON event with a schema (e.g., `{"channel_id": "...", "content": "..."}`)
- A structured command from an orchestrator

## io:stdout

Your primary output channel. This is how you return results to your cog.

**If your cog declared an output schema**, write JSON that conforms to it. Your message will be validated — schema violations are rejected and logged to `io:stderr`.

```python
# Structured output (when schema is set)
channels.send("io:stdout", {"status": "complete", "result": summary})
```

**If no schema was declared**, write plain text.

```python
# Free-form output
channels.send("io:stdout", "Task complete. Created 3 files.")
```

**When to write:**
- When you've completed your task or a significant milestone
- When you have a partial result worth surfacing early
- Don't write conversational filler — only meaningful output

## io:stderr

Diagnostics and errors. Use this like Unix stderr — anything that isn't primary output.

```python
# Errors
channels.send("io:stderr", "ERROR: Failed to connect to API: 401 Unauthorized")

# Warnings
channels.send("io:stderr", "WARN: Rate limited, retrying in 5s")

# Debug/progress
channels.send("io:stderr", "DEBUG: Processing batch 3/10")
```

## cog:from

Messages from your parent cog, injected directly into your conversation context. You don't need to read this channel explicitly — messages appear as naturally as any other input.

**What your cog sends you:**
- **Suggestions** — better approaches, patterns to try, code improvements
- **Requests** — "also handle edge case X", "prioritize Y"
- **Updates** — context changes, new information relevant to your task
- **Corrections** — "that output was wrong because...", "retry with these constraints"

Your cog is responsible for helping you succeed. Treat its messages as authoritative guidance — act on them.

## cog:to

Your explicit channel for communicating back to your parent cog. Unlike `io:stdout` (which is your task output), `cog:to` is for the relationship with your cog.

```python
# Status update
channels.send("cog:to", {"type": "status", "msg": "Halfway through, found 3 issues so far"})

# Ask for help
channels.send("cog:to", {"type": "help", "msg": "I don't have access to the payments API"})

# Report a decision
channels.send("cog:to", {"type": "decision", "msg": "Using batch processing — dataset too large for single pass"})
```

**When to write:**
- When you hit a blocker your cog might resolve
- When you make a significant decision your cog should know about
- When you have a progress update worth sharing
- Don't spam — your cog has other things to do

## The cog's perspective

Your parent cog created you to handle a specific task. It reads `cog:to` for your updates and sends guidance via `cog:from`. It does not monitor your `io:*` channels — those are for your task input and output. Think of it as a senior colleague who set you up with a task and checks in periodically.
