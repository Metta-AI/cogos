"""Email ingest Lambda — receives parsed emails from Cloudflare Email Worker.

Resolves the target cogent's DB name from DynamoDB,
then inserts the event via RDS Data API using the shared Aurora cluster.
"""

import base64
import hmac
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INGEST_SECRET = os.environ.get("EMAIL_INGEST_SECRET", "")
DB_CLUSTER_ARN = os.environ.get("DB_CLUSTER_ARN", "")
DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN", "")
DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "")

_rds: Any = None
_dynamo_table: Any = None

# Cache: cogent_name -> db_name
_db_name_cache: dict[str, str] = {}


def _get_rds():
    global _rds
    if _rds is None:
        _rds = boto3.client("rds-data")
    return _rds


def _get_dynamo_table():
    global _dynamo_table
    if _dynamo_table is None:
        _dynamo_table = boto3.resource("dynamodb").Table(DYNAMO_TABLE)  # type: ignore[attr-defined]
    return _dynamo_table


def _resolve_db_name(cogent_name: str) -> str:
    """Resolve a cogent's db_name from the DynamoDB status table."""
    if cogent_name in _db_name_cache:
        return _db_name_cache[cogent_name]

    resp = _get_dynamo_table().get_item(Key={"cogent_name": cogent_name})
    item = resp.get("Item")
    if not item:
        raise ValueError(f"Cogent not found in status table: {cogent_name}")

    db_name = item.get("db_name")
    if not db_name:
        raise ValueError(f"Cogent {cogent_name} has no db_name in status table")

    _db_name_cache[cogent_name] = db_name
    return db_name


def _insert_event(cogent_name: str, event_type: str, source: str, payload: dict) -> str:
    """Insert an event into the cogent's cogos_event table via Data API."""
    db_name = _resolve_db_name(cogent_name)
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    _get_rds().execute_statement(
        resourceArn=DB_CLUSTER_ARN,
        secretArn=DB_SECRET_ARN,
        database=db_name,
        sql="""
            INSERT INTO cogos_event (id, event_type, source, payload, created_at)
            VALUES (:id::uuid, :event_type, :source, :payload::jsonb, :created_at::timestamptz)
        """,
        parameters=[
            {"name": "id", "value": {"stringValue": event_id}},
            {"name": "event_type", "value": {"stringValue": event_type}},
            {"name": "source", "value": {"stringValue": source}},
            {"name": "payload", "value": {"stringValue": json.dumps(payload)}},
            {"name": "created_at", "value": {"stringValue": now}},
        ],
    )
    return event_id


def _extract_asana_accept_link(html_body: str) -> str | None:
    """Extract Asana invitation accept link from email HTML body."""
    pattern = r'href="(https://app\.asana\.com/[^"]*)"'
    for m in re.finditer(pattern, html_body):
        url = m.group(1)
        if "accept" in url or "invitation" in url:
            return url
    return None


def _try_asana_auto_accept(cogent_name: str, payload: dict) -> None:
    """If the email is an Asana invite, auto-accept and update DynamoDB status."""
    sender = str(payload.get("from", ""))
    if "asana.com" not in sender.lower():
        return

    html_body = payload.get("html_body", "") or payload.get("body", "")
    link = _extract_asana_accept_link(html_body)
    if not link:
        logger.warning("No accept link in Asana email cogent=%s subject=%s", cogent_name, payload.get("subject"))
        return

    logger.info("Auto-accepting Asana invite cogent=%s", cogent_name)
    resp = requests.get(link, allow_redirects=True, timeout=30)
    if resp.status_code < 400:
        logger.info("Asana invite accepted cogent=%s", cogent_name)
        _get_dynamo_table().update_item(
            Key={"cogent_name": cogent_name},
            UpdateExpression="SET asana_status = :s",
            ExpressionAttributeValues={":s": "active"},
        )
    else:
        logger.error("Failed to accept Asana invite cogent=%s status=%s", cogent_name, resp.status_code)


def handler(event, context):
    """Lambda handler — expects API Gateway / Function URL proxy event."""
    headers = event.get("headers", {})
    auth = headers.get("authorization", headers.get("Authorization", ""))
    token = auth.removeprefix("Bearer ").strip()

    if not INGEST_SECRET or not hmac.compare_digest(token, INGEST_SECRET):
        return {"statusCode": 401, "body": json.dumps({"detail": "Invalid ingest token"})}

    try:
        raw_body = event.get("body", "{}")
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode()
        body = json.loads(raw_body)
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("Failed to parse body: %s, raw=%s", exc, event.get("body", "")[:200])
        return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

    payload = body.get("payload", {})
    cogent_name = payload.get("cogent")
    if not cogent_name:
        return {"statusCode": 400, "body": json.dumps({"detail": "Missing cogent in payload"})}

    event_type = body.get("event_type", "email:received")
    source = body.get("source", "cloudflare-email-worker")

    try:
        event_id = _insert_event(cogent_name, event_type, source, payload)
    except Exception:
        logger.exception("Failed to insert event for cogent=%s", cogent_name)
        return {"statusCode": 500, "body": json.dumps({"detail": "Failed to insert event"})}

    logger.info(
        "Ingested email event %s cogent=%s from=%s subject=%s",
        event_id, cogent_name, payload.get("from"), payload.get("subject"),
    )

    try:
        _try_asana_auto_accept(cogent_name, payload)
    except Exception:
        logger.exception("Asana auto-accept failed cogent=%s", cogent_name)

    return {"statusCode": 200, "body": json.dumps({"event_id": event_id})}
