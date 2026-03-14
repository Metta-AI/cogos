# Secret audit app — demonstrate file-system discovery with least-privilege
# verification against the secret store.

add_schema(
    "secret-audit-request",
    definition={
        "fields": {
            "prefix": "string",
            "report_key": "string",
            "reason": "string",
            "secret_keys": "list[string]",
        }
    },
)

add_schema(
    "secret-audit-event",
    definition={
        "fields": {
            "job_id": "string",
            "stage": "string",
            "status": "string",
            "artifact_key": "string",
            "item_count": "number",
            "summary": "string",
        }
    },
)

add_schema(
    "secret-audit-finding",
    definition={
        "fields": {
            "job_id": "string",
            "status": "string",
            "report_key": "string",
            "confirmed_live_secrets": "number",
            "needs_review": "number",
            "summary": "string",
        }
    },
)

add_channel(
    "secret-audit:requests",
    schema="secret-audit-request",
    channel_type="named",
)
add_channel(
    "secret-audit:events",
    schema="secret-audit-event",
    channel_type="named",
)
add_channel(
    "secret-audit:findings",
    schema="secret-audit-finding",
    channel_type="named",
)

add_process(
    "secret-audit",
    mode="daemon",
    content="@{apps/secret-audit/orchestrator.md}",
    runner="lambda",
    priority=4.0,
    capabilities=[
        "me", "procs", "dir", "file", "channels", "secrets", "stdlib",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/secret-audit/"}},
    ],
    handlers=["secret-audit:requests", "secret-audit:events", "system:tick:hour"],
)
