"""Agent Watcher Lambda: polls CloudFormation + ECS for all cogent stacks,
writes status to DynamoDB for instant CLI reads.

Runs on a 1-minute EventBridge schedule. Uses only stdlib + boto3.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import boto3

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

    channels_map = _poll_channels(sm_client)
    now = int(time.time())
    seen_names: set[str] = set()
    items: list[dict] = []

    for st in stacks:
        stack_name = st["Name"]
        stack_status = st["Status"]
        cogent_name = stack_name.removeprefix("cogent-")
        running_count = 0
        desired_count = 0
        image_tag = "-"
        cluster_name = None
        service_name = None

        try:
            resp = cfn.describe_stacks(StackName=stack_name)
            outputs = {
                o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])
            }
            cogent_name = outputs.get("CogentName", cogent_name)
            image_tag = outputs.get("ImageTag", "-")

            cluster_arn = outputs.get("ClusterArn")
            service_name = outputs.get("ServiceName")
            if cluster_arn:
                cluster_name = cluster_arn.split("/")[-1]
            if cluster_arn and service_name:
                svc = ecs.describe_services(cluster=cluster_arn, services=[service_name])
                if svc["services"]:
                    s = svc["services"][0]
                    running_count = s.get("runningCount", 0)
                    desired_count = s.get("desiredCount", 0)
        except Exception:
            logger.exception("Error polling stack %s", stack_name)

        seen_names.add(cogent_name)
        items.append(
            {
                "cogent_name": cogent_name,
                "stack_name": stack_name,
                "stack_status": stack_status,
                "running_count": running_count,
                "desired_count": desired_count,
                "image_tag": image_tag,
                "channels": channels_map.get(cogent_name, {}),
                "_cluster_name": cluster_name,
                "_service_name": service_name,
                "updated_at": now,
            }
        )

    metrics = _poll_metrics(cw, items)

    with table.batch_writer() as batch:
        for item in items:
            name = item["cogent_name"]
            m = metrics.get(name, {})
            item["cpu_1m"] = m.get("cpu_1m", 0)
            item["cpu_10m"] = m.get("cpu_10m", 0)
            item["mem_pct"] = m.get("mem_pct", 0)
            item.pop("_cluster_name", None)
            item.pop("_service_name", None)
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


def _poll_metrics(cw, items: list[dict]) -> dict[str, dict[str, int]]:
    """Batch-query CloudWatch for CPU and memory utilization."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=12)

    queries = []
    id_map: dict[str, tuple[str, str]] = {}

    for i, item in enumerate(items):
        cluster = item.get("_cluster_name")
        service = item.get("_service_name")
        if not cluster or not service:
            continue

        name = item["cogent_name"]
        dims = [
            {"Name": "ClusterName", "Value": cluster},
            {"Name": "ServiceName", "Value": service},
        ]

        cpu_id = f"c{i}"
        queries.append(
            {
                "Id": cpu_id,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/ECS",
                        "MetricName": "CPUUtilization",
                        "Dimensions": dims,
                    },
                    "Period": 60,
                    "Stat": "Average",
                },
            }
        )
        id_map[cpu_id] = (name, "cpu")

        mem_id = f"m{i}"
        queries.append(
            {
                "Id": mem_id,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/ECS",
                        "MetricName": "MemoryUtilization",
                        "Dimensions": dims,
                    },
                    "Period": 60,
                    "Stat": "Average",
                },
            }
        )
        id_map[mem_id] = (name, "mem")

    if not queries:
        return {}

    results: dict[str, dict[str, int]] = {}
    try:
        for chunk_start in range(0, len(queries), 500):
            chunk = queries[chunk_start : chunk_start + 500]
            resp = cw.get_metric_data(
                MetricDataQueries=chunk, StartTime=start, EndTime=now
            )
            for mr in resp["MetricDataResults"]:
                qid = mr["Id"]
                if qid not in id_map:
                    continue
                name, metric_type = id_map[qid]
                values = mr.get("Values", [])
                if name not in results:
                    results[name] = {}
                if values:
                    if metric_type == "cpu":
                        results[name]["cpu_1m"] = round(values[0])
                        results[name]["cpu_10m"] = round(sum(values) / len(values))
                    elif metric_type == "mem":
                        results[name]["mem_pct"] = round(values[0])
    except Exception:
        logger.exception("Error polling CloudWatch metrics")

    return results


def _cleanup_stale(table, seen_names: set[str]) -> None:
    """Remove DynamoDB entries for cogents that no longer have stacks."""
    try:
        resp = table.scan(ProjectionExpression="cogent_name")
        for item in resp.get("Items", []):
            name = item["cogent_name"]
            if name not in seen_names:
                table.delete_item(Key={"cogent_name": name})
                logger.info("Cleaned up stale entry: %s", name)
    except Exception:
        logger.exception("Error cleaning up stale entries")
