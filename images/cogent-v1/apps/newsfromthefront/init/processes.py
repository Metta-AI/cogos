# Newsfromthefront process is now managed as a cog.
# See cog.py in this directory for the default coglet declaration.

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
