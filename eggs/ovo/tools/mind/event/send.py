from brain.db.models import Tool

tool = Tool(
    description="Send an event to the event bus.",
    instructions="Use this to emit events that can trigger other programs.",
    handler="brain.tools.handlers:event_send",
    input_schema={
        "type": "object",
        "properties": {
            "event_type": {"type": "string", "description": "The event type"},
            "payload": {"type": "object", "description": "JSON payload", "default": {}},
        },
        "required": ["event_type"],
    },
)
