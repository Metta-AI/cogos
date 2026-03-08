from brain.db.models import Tool

tool = Tool(
    description="Retrieve a memory value by key name.",
    instructions="Use this to read stored memory values. Pass the exact key name.",
    handler="brain.tools.handlers:memory_get",
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The memory key to retrieve"},
        },
        "required": ["key"],
    },
)
