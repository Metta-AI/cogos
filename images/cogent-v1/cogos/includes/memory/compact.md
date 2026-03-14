# Memory Policy: Compact

You maintain two files: `data/session.md` for recent activity and `data/summary.md` for long-term learnings. Before old session entries are discarded, they're distilled into the summary.

## On Startup

1. Read `data/summary.md` — your long-term memory. Accumulated learnings, patterns, key events.
2. Read `data/session.md` — recent activity for immediate context.

Use both to orient yourself before doing any work.

## During Execution

After each meaningful action, append a timestamped entry to `data/session.md`:

```
--- YYYY-MM-DDTHH:MM:SSZ
[one-line summary of what happened]
[key details: decisions made, inputs received, outputs produced]
```

What counts as meaningful: user interactions, state changes, decisions, errors, completions. Skip routine no-ops.

## Maintenance

After appending, if `data/session.md` exceeds 200 lines:

1. Read all of `data/session.md` and `data/summary.md`.
2. From the older entries (everything except the last 50 lines), identify anything worth remembering long-term:
   - Patterns noticed, preferences learned
   - Decisions made and why
   - Outcomes — what worked, what didn't
   - Facts that will be useful in future runs
3. Append a new section to `data/summary.md` with those learnings. Don't repeat what's already there.
4. Truncate `data/session.md` to the last 50 lines.

## Bootstrap

If `data/summary.md` doesn't exist, create it:

```
# Summary
```

If `data/session.md` doesn't exist, create it:

```
# Session Log
```

Then write your first entry.
