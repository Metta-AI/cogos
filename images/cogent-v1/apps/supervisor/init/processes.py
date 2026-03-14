# Supervisor app — reactive help handler for processes that can't handle their work.

add_schema(
    "supervisor-help-request",
    definition={
        "fields": {
            "process_name": "string",
            "description": "string",
            "context": "string",
            "severity": "string",
            "reply_channel": "string",
            "discord_channel_id": "string",
            "discord_message_id": "string",
            "discord_author_id": "string",
        }
    },
)

add_channel(
    "supervisor:help",
    schema="supervisor-help-request",
    channel_type="named",
)

add_process(
    "supervisor",
    mode="daemon",
    content="@{apps/supervisor/supervisor.md}",
    runner="lambda",
    priority=8.0,
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "secrets", "stdlib", "alerts", "email",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/supervisor/"}},
    ],
    handlers=["supervisor:help"],
)
