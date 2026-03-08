from brain.db.models import Tool

tool = Tool(
    description="Check Gmail inbox for messages.",
    instructions="Search Gmail for messages. Returns recent messages matching the query.",
    handler="brain.tools.handlers:gmail_check",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query (e.g. 'is:unread')", "default": "is:unread"},
            "max_results": {"type": "integer", "description": "Max messages to return", "default": 10},
        },
    },
)
