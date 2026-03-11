"""Agent Watcher Lambda: polls CloudFormation + ECS for all cogent stacks,
writes status to DynamoDB for instant CLI reads.

Runs on a 1-minute EventBridge schedule. Uses only stdlib + boto3.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3

from polis.runtime_status import load_status_manifest, resolve_runtime_status

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DYNAMO_TABLE = os.environ.get("DYNAMO_TABLE", "cogent-status")
ACTIVE_STATUSES = [
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE",
    "CREATE_IN_PROGRESS",
    "UPDATE_IN_PROGRESS",
]


def handler(event, context):
    logger.info("Event: %s", json.dumps(event))

    cfn = boto3.client("cloudformation")
    ecs = boto3.client("ecs")
    sm_client = boto3.client("secretsmanager")
    cw = boto3.client("cloudwatch")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(DYNAMO_TABLE)

    stacks = _find_cogent_stacks(cfn)
    logger.info("Found %d cogent stacks", len(stacks))

    existing_items = _load_existing_status_items(table)
    existing_by_name = {item["cogent_name"]: item for item in existing_items if item.get("cogent_name")}
    existing_by_stack = {item["stack_name"]: item for item in existing_items if item.get("stack_name")}

    channels_map = _poll_channels(sm_client)
    now = int(time.time())
    seen_names: set[str] = set()
    items: list[dict] = []

    for st in stacks:
        stack_name = st["Name"]
        stack_status = st["Status"]

        try:
            resp = cfn.describe_stacks(StackName=stack_name)
            stack = resp["Stacks"][0]
            manifest = load_status_manifest(stack)
            cogent_name = manifest["cogent_name"]
            existing = existing_by_name.get(cogent_name) or existing_by_stack.get(stack_name, {})
            items.append(
                resolve_runtime_status(
                    ecs_client=ecs,
                    cloudwatch_client=cw,
                    stack_name=stack_name,
                    stack_status=stack_status,
                    manifest=manifest,
                    existing=existing,
                    channels=channels_map.get(cogent_name, {}),
                    updated_at=now,
                )
            )
            seen_names.add(cogent_name)
        except Exception:
            logger.exception("Error polling stack %s", stack_name)
            existing = existing_by_stack.get(stack_name, {})
            if existing.get("cogent_name"):
                seen_names.add(existing["cogent_name"])

    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    _cleanup_stale(table, seen_names)
    logger.info("Wrote %d items to %s", len(seen_names), DYNAMO_TABLE)
    return {"statusCode": 200, "cogents": len(seen_names)}


def _find_cogent_stacks(cfn) -> list[dict]:
    """List all cogent-* CloudFormation stacks."""
    stacks = []
    paginator = cfn.get_paginator("list_stacks")
    for page in paginator.paginate(StackStatusFilter=ACTIVE_STATUSES):
        for s in page["StackSummaries"]:
            name = s["StackName"]
            if name.startswith("cogent-") and name not in ("cogent-polis", "cogent-secrets"):
                stacks.append({"Name": name, "Status": s["StackStatus"]})
    return sorted(stacks, key=lambda s: s["Name"])


def _load_existing_status_items(table) -> list[dict]:
    """Load existing cogent status rows from DynamoDB."""
    items: list[dict] = []
    params = {}
    while True:
        resp = table.scan(**params)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        params["ExclusiveStartKey"] = last_key
    return items


def _poll_channels(sm_client) -> dict[str, dict[str, str]]:
    """Group channel status by cogent from secrets.

    Returns {cogent_name: {channel: "ok"|"stale"}}.
    """
    result: dict[str, dict[str, str]] = {}
    now = datetime.now(timezone.utc)
    try:
        paginator = sm_client.get_paginator("list_secrets")
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": ["cogent/"]}]):
            for s in page["SecretList"]:
                parts = s["Name"].split("/")
                # cogent/{cogent_name}/{channel}
                if len(parts) != 3:
                    continue
                cogent_name = parts[1]
                channel = parts[2]
                last_accessed = s.get("LastAccessedDate")
                if last_accessed:
                    age = (now - last_accessed.astimezone(timezone.utc)).total_seconds()
                    status = "ok" if age < 86400 else "stale"
                else:
                    status = "stale"
                result.setdefault(cogent_name, {})[channel] = status
    except Exception:
        logger.exception("Error polling channels")
    return result


def _cleanup_stale(table, seen_names: set[str]) -> None:
    """Remove DynamoDB entries for cogents that no longer have stacks.

    Preserves REGISTERED entries (created by `polis cogents create` but
    not yet deployed).
    """
    try:
        params = {"ProjectionExpression": "cogent_name, stack_status"}
        while True:
            resp = table.scan(**params)
            for item in resp.get("Items", []):
                name = item["cogent_name"]
                status = item.get("stack_status", "")
                if name not in seen_names and status != "REGISTERED":
                    table.delete_item(Key={"cogent_name": name})
                    logger.info("Cleaned up stale entry: %s", name)
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            params["ExclusiveStartKey"] = last_key
    except Exception:
        logger.exception("Error cleaning up stale entries")
