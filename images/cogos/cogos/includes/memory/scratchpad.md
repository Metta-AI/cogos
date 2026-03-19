# Memory Policy: Scratchpad

You use `data/scratchpad.md` as ephemeral working memory — a whiteboard for plans, intermediate results, and in-progress work. It is not a permanent record.

## On Startup

Read `data/scratchpad.md`. If it contains anything from a previous session, treat it as stale context — useful for understanding what was in progress, but not authoritative. Clear it after reading.

## During Execution

Use `data/scratchpad.md` freely as working memory:
- Plans and next steps for multi-step tasks
- Intermediate results you'll need in later steps
- Draft outputs being assembled across multiple actions

Overwrite the file as needed — this is not a log, it's a whiteboard.

## On Completion

When your current task or run is complete, clear `data/scratchpad.md`:

```
# Scratchpad
```

## Bootstrap

If `data/scratchpad.md` doesn't exist, create it:

```
# Scratchpad
```
