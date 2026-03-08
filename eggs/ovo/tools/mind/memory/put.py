from brain.db.models import Tool

tool = Tool(
    description="Store a value in memory under a key name.",
    instructions="Use this to store values. Provide both key and value.",
    handler="brain.tools.handlers:memory_put",
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The memory key name"},
            "value": {"type": "string", "description": "The value to store"},
        },
        "required": ["key", "value"],
    },
)
