# newsfromthefront Test Runner

@{cogos/includes/memory/session.md}

You run an end-to-end competitive analysis loop for testing. This never touches
the production knowledge base — it is safe to run at any time.

### 1. Check mode

```python
if payload["mode"] != "test":
    print("Not a test request — exiting.")
    exit()
```

### 2. Run researcher logic inline

Follow the same steps as the researcher prompt (`apps/newsfromthefront/researcher.md`),
but set `is_test = True` in the findings-ready message:

```python
channels.send("newsfromthefront:findings-ready", {
    "run_id": run_id,
    "findings_key": findings_key,
    "date": today,
    "is_test": True,
    "is_backfill": False,
})
```

The analyst will handle the rest, skip KB updates, and post to a labeled test thread.

## Notes

- The test is triggered by `@cogent test` in any Discord channel.
- `discord-handle-message` detects the "test" command and sends to `newsfromthefront:run-requested`
  with `{"mode": "test", "after_date": "", "before_date": ""}`.
- Results appear in a thread titled "Newsfromthefront TEST — `<date>`".
