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

# ── Processes ─────────────────────────────────────────────────────────────────

_HAIKU  = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_SONNET = "us.anthropic.claude-sonnet-4-6-20251101-v1:0"

add_process(
    "newsfromthefront-researcher",
    mode="daemon",
    code_key="newsfromthefront/researcher",
    runner="lambda",
    model=_SONNET,
    priority=15.0,
    capabilities=["web_search", "dir", "channels", "secrets"],
    handlers=["newsfromthefront:tick"],
)

add_process(
    "newsfromthefront-analyst",
    mode="daemon",
    code_key="newsfromthefront/analyst",
    runner="lambda",
    model=_SONNET,
    priority=15.0,
    capabilities=["dir", "channels", "discord", "secrets"],
    handlers=["newsfromthefront:findings-ready", "newsfromthefront:discord-feedback"],
)

add_process(
    "newsfromthefront-test",
    mode="daemon",
    code_key="newsfromthefront/test",
    runner="lambda",
    model=_SONNET,
    priority=20.0,
    capabilities=["web_search", "dir", "channels", "discord", "secrets"],
    handlers=["newsfromthefront:run-requested"],
)

add_process(
    "newsfromthefront-backfill",
    mode="daemon",
    code_key="newsfromthefront/backfill",
    runner="lambda",
    model=_HAIKU,
    priority=5.0,
    capabilities=["web_search", "dir", "channels", "discord", "secrets"],
    handlers=["newsfromthefront:run-requested"],
)
