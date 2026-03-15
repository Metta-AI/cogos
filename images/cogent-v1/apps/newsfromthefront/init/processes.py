# ── Schemas ───────────────────────────────────────────────────────────────────

add_schema("newsfromthefront_findings_ready", definition={
    "fields": {
        "run_id":       "string",
        "findings_key": "string",
        "date":         "string",
        "is_test":      "bool",
        "is_backfill":  "bool",
    },
})

add_schema("newsfromthefront_discord_feedback", definition={
    "fields": {
        "thread_id": "string",
        "content":   "string",
        "author":    "string",
    },
})

add_schema("newsfromthefront_run_requested", definition={
    "fields": {
        "mode":        "string",
        "after_date":  "string",
        "before_date": "string",
    },
})

# ── Channels ──────────────────────────────────────────────────────────────────

add_channel("newsfromthefront:tick",             channel_type="named")
add_channel("newsfromthefront:findings-ready",   schema="newsfromthefront_findings_ready")
add_channel("newsfromthefront:discord-feedback", schema="newsfromthefront_discord_feedback")
add_channel("newsfromthefront:run-requested",    schema="newsfromthefront_run_requested")

# ── Root orchestrator ────────────────────────────────────────────────────────
# Single daemon that spawns researcher, analyst, backfill, and test as children.

add_process(
    "newsfromthefront",
    mode="daemon",
    content="@{apps/newsfromthefront/newsfromthefront.md}",
    runner="lambda",
    priority=15.0,
    capabilities=[
        "me", "procs", "dir", "file", "channels", "discord",
        "web_search", "secrets", "stdlib",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/newsfromthefront/"}},
    ],
    handlers=[
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ],
)
