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
