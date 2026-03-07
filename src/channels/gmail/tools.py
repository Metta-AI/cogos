"""Gmail tool definitions and execution for the executor Lambda."""

from __future__ import annotations

import json

import boto3

from channels.gmail.poller import GmailClient
from channels.gmail.sender import GmailSender

TOOL_SCHEMAS: dict[str, dict] = {
    "gmail_check": {
        "description": "Check Gmail inbox for messages. Returns recent unread messages or searches with a query.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query (e.g. 'is:unread', 'from:user@example.com')", "default": "is:unread"},
                "max_results": {"type": "integer", "description": "Max messages to return", "default": 10},
            },
        }},
    },
    "gmail_send": {
        "description": "Send an email via Gmail.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["to", "subject", "body"],
        }},
    },
}


def get_gmail_client(cogent_name: str, region: str) -> GmailClient:
    """Build a GmailClient from Secrets Manager credentials."""
    sm = boto3.client("secretsmanager", region_name=region)
    secret = sm.get_secret_value(SecretId=f"cogent/{cogent_name}/google-admin")
    creds = json.loads(secret["SecretString"])
    return GmailClient(
        service_account_key=creds["service_account_key"],
        impersonate_email=creds["impersonate_email"],
        scopes=creds.get("scopes", [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ]),
    )


def execute_tool(tool_name: str, tool_input: dict, cogent_name: str, region: str) -> str:
    """Execute a Gmail tool and return the result as a string."""
    if tool_name == "gmail_check":
        return _check(tool_input, cogent_name, region)
    elif tool_name == "gmail_send":
        return _send(tool_input, cogent_name, region)
    else:
        return f"Unknown gmail tool: {tool_name}"


def _check(tool_input: dict, cogent_name: str, region: str) -> str:
    query = tool_input.get("query", "is:unread") or "is:unread"
    max_results = tool_input.get("max_results", 10) or 10
    client = get_gmail_client(cogent_name, region)
    profile = client.get_profile()
    messages = client.list_messages(query=query, max_results=max_results)
    if not messages:
        return json.dumps({
            "email": profile.get("emailAddress"),
            "query": query,
            "count": 0,
            "messages": [],
        })
    results = []
    for stub in messages[:max_results]:
        msg = client.get_message_metadata(stub["id"])
        headers = {}
        for h in msg.get("payload", {}).get("headers", []):
            headers[h["name"].lower()] = h["value"]
        results.append({
            "id": stub["id"],
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
        })
    return json.dumps({
        "email": profile.get("emailAddress"),
        "query": query,
        "count": len(results),
        "messages": results,
    })


def _send(tool_input: dict, cogent_name: str, region: str) -> str:
    to = tool_input.get("to", "").strip()
    subject = tool_input.get("subject", "").strip()
    body = tool_input.get("body", "")
    if not to or not subject:
        return "Error: gmail_send requires 'to' and 'subject'"
    client = get_gmail_client(cogent_name, region)
    sender = GmailSender(client)
    result = sender.send_email(to=to, subject=subject, body=body)
    return json.dumps({"sent": True, "message_id": result.get("id", ""), "to": to, "subject": subject})
