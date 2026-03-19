# Memory Policy: Session Log

You maintain a running session log. This is your short-term memory — what happened, when, and why.

## How to use

```python
# Read (returns content string, or empty if file doesn't exist yet)
log = data.get("session.md")
history = log.read()
print(history.content if not hasattr(history, 'error') else "")

# Append a timestamped entry (creates the file if missing)
log.append(f"\n--- {stdlib.time.strftime('%Y-%m-%dT%H:%M:%SZ', stdlib.time.gmtime())}\nSummary of what happened")

# Read the full log after appending
print(log.read().content)
```

## When to write

After each meaningful action, append a one-line timestamped entry. What counts: user interactions, state changes, decisions, errors. Skip routine no-ops.

## Maintenance

If the log exceeds 200 lines, trim by overwriting:
```python
lines = log.read().content.split("\n")
if len(lines) > 200:
    log.write("\n".join(lines[-150:]))
```
