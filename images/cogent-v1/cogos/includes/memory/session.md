# Memory Policy: Session Log

You maintain a running session log in `data/session.md`. This is your short-term memory — what happened, when, and why.

## On Startup

Read `data/session.md`. Use it to orient yourself — what happened recently, where you left off, what's in progress.

## During Execution

After each meaningful action, append a timestamped entry to `data/session.md`:

```
--- YYYY-MM-DDTHH:MM:SSZ
[one-line summary of what happened]
[key details: decisions made, inputs received, outputs produced]
```

What counts as meaningful: user interactions, state changes, decisions, errors, completions. Skip routine no-ops.

## Maintenance

After appending, if `data/session.md` exceeds 200 lines, delete everything before the most recent 150 lines. Oldest entries are lost — if you need durable memory, use the `compact` or `knowledge` policy instead.

## Bootstrap

If `data/session.md` doesn't exist, create it:

```
# Session Log
```

Then write your first entry.
