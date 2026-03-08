from brain.db.models import Tool

tool = Tool(
    description="Send an email via Gmail.",
    instructions="Send an email. Requires to, subject, and body.",
    handler="brain.tools.handlers:gmail_send",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body text"},
        },
        "required": ["to", "subject", "body"],
    },
)
