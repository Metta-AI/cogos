"""Resolve canonical runtime status snapshots for cogent stacks."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PRIMARY_COMPONENTS = ("dashboard", "discord", "executor")
_SERVICE_COMPONENTS = ("dashboard", "discord")


def load_status_manifest(stack: dict[str, Any]) -> dict[str, Any]:
    """Load and normalize the stack's status manifest.

    The manifest is the stable contract between the brain stack and the
    watcher. Older stacks may not have the output yet, so we preserve a small
    fallback that still requires explicit identity from tags or outputs.
    """
    outputs = _outputs_by_key(stack)
    tags = _tags_by_key(stack)

    raw_manifest = outputs.get("StatusManifest")
    if raw_manifest:
        try:
            manifest = json.loads(raw_manifest)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid StatusManifest JSON: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("StatusManifest must decode to an object")
    else:
        manifest = {}

    cogent_name = str(
        manifest.get("cogent_name")
        or tags.get("cogent_name")
        or outputs.get("CogentName")
        or ""
    ).strip()
    if not cogent_name:
        raise ValueError("Stack is missing StatusManifest.cogent_name and cogent_name tag")

    normalized: dict[str, Any] = {
        "version": int(manifest.get("version") or (1 if raw_manifest else 0)),
        "cogent_name": cogent_name,
    }

    for component_name in _PRIMARY_COMPONENTS:
        component = manifest.get(component_name)
        if isinstance(component, dict) and component:
            normalized[component_name] = dict(component)

    dashboard = dict(normalized.get("dashboard") or {})
    if outputs.get("DashboardUrl") and not dashboard.get("url"):
        dashboard["url"] = outputs["DashboardUrl"]
    if dashboard:
        normalized["dashboard"] = dashboard

    return normalized


def resolve_runtime_status(
    *,
    ecs_client,
    cloudwatch_client,
    stack_name: str,
    stack_status: str,
    manifest: dict[str, Any],
    existing: dict[str, Any] | None = None,
    channels: dict[str, str] | None = None,
    updated_at: int | None = None,
) -> dict[str, Any]:
    """Resolve a canonical runtime snapshot from the manifest."""
    existing = existing or {}
    components = _resolve_components(ecs_client, cloudwatch_client, manifest)
    summary = _primary_summary_component(components)
    dashboard = components.get("dashboard", {})
    dashboard_url = dashboard.get("url") or existing.get("dashboard_url")
    if not dashboard_url:
        dashboard_url = (
            (manifest.get("dashboard") or {}).get("url")
            if isinstance(manifest.get("dashboard"), dict)
            else None
        )

    snapshot: dict[str, Any] = {
        "cogent_name": manifest["cogent_name"],
        "stack_name": stack_name,
        "stack_status": stack_status,
        "channels": channels or {},
        "status_manifest": manifest,
        "manifest_version": int(manifest.get("version") or 0),
        "running_count": int(summary.get("running_count") or 0),
        "desired_count": int(summary.get("desired_count") or 0),
        "image_tag": summary.get("image") or "-",
        "cpu_1m": int(summary.get("cpu_1m") or 0),
        "cpu_10m": int(summary.get("cpu_10m") or 0),
        "mem_pct": int(summary.get("mem_pct") or 0),
        "updated_at": int(updated_at or time.time()),
    }

    for key in ("domain", "certificate_arn"):
        if existing.get(key):
            snapshot[key] = existing[key]

    if dashboard_url:
        snapshot["dashboard_url"] = dashboard_url
        if not snapshot.get("domain"):
            parsed = urlparse(str(dashboard_url))
            if parsed.netloc:
                snapshot["domain"] = parsed.netloc

    for component_name, component in components.items():
        if component:
            snapshot[component_name] = component

    return snapshot


def _resolve_components(ecs_client, cloudwatch_client, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    task_definition_cache: dict[str, dict[str, Any]] = {}
    service_refs: dict[str, tuple[str, str]] = {}

    for component_name in _SERVICE_COMPONENTS:
        component_manifest = _component_manifest(manifest, component_name)
        if not component_manifest:
            continue
        component, service_ref = _resolve_service_component(
            ecs_client=ecs_client,
            component_name=component_name,
            component_manifest=component_manifest,
            task_definition_cache=task_definition_cache,
        )
        components[component_name] = component
        if service_ref:
            service_refs[component_name] = service_ref

    executor_manifest = _component_manifest(manifest, "executor")
    if executor_manifest:
        components["executor"] = _resolve_task_definition_component(
            ecs_client=ecs_client,
            component_manifest=executor_manifest,
            task_definition_cache=task_definition_cache,
        )

    _attach_service_metrics(cloudwatch_client, components, service_refs)
    return components


def _resolve_service_component(
    *,
    ecs_client,
    component_name: str,
    component_manifest: dict[str, Any],
    task_definition_cache: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], tuple[str, str] | None]:
    component: dict[str, Any] = dict(component_manifest)
    service_arn = str(component_manifest.get("service_arn") or "").strip()
    if not service_arn:
        return component, None

    component["service_arn"] = service_arn

    try:
        cluster_name, service_name = _service_identity_from_arn(service_arn)
        resp = ecs_client.describe_services(cluster=cluster_name, services=[service_arn])
        services = resp.get("services", [])
        if not services:
            component["status"] = "MISSING"
            return component, (cluster_name, service_name)

        service = services[0]
        task_definition_arn = str(service.get("taskDefinition") or "").strip()
        component.update(
            {
                "cluster_name": cluster_name,
                "service_name": str(service.get("serviceName") or service_name),
                "status": str(service.get("status") or "-"),
                "running_count": int(service.get("runningCount") or 0),
                "desired_count": int(service.get("desiredCount") or 0),
                "task_definition_arn": task_definition_arn,
            }
        )
        if task_definition_arn:
            component["image"] = _task_definition_image(
                ecs_client=ecs_client,
                task_definition_arn=task_definition_arn,
                container_name=component.get("container_name"),
                task_definition_cache=task_definition_cache,
            ) or "-"
    except Exception as exc:
        logger.exception("Failed to resolve %s runtime state", component_name)
        component["status"] = "ERROR"
        component["error"] = str(exc)
        return component, None

    if component_name == "dashboard" and component_manifest.get("url"):
        component["url"] = component_manifest["url"]

    return component, (component["cluster_name"], component["service_name"])


def _resolve_task_definition_component(
    *,
    ecs_client,
    component_manifest: dict[str, Any],
    task_definition_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    component: dict[str, Any] = dict(component_manifest)
    task_definition_arn = str(component_manifest.get("task_definition_arn") or "").strip()
    if not task_definition_arn:
        return component

    component["task_definition_arn"] = task_definition_arn
    try:
        component["image"] = _task_definition_image(
            ecs_client=ecs_client,
            task_definition_arn=task_definition_arn,
            container_name=component.get("container_name"),
            task_definition_cache=task_definition_cache,
        ) or "-"
    except Exception as exc:
        logger.exception("Failed to resolve executor task definition image")
        component["error"] = str(exc)
    return component


def _attach_service_metrics(
    cloudwatch_client,
    components: dict[str, dict[str, Any]],
    service_refs: dict[str, tuple[str, str]],
) -> None:
    queries: list[dict[str, Any]] = []
    query_map: dict[str, tuple[str, str]] = {}

    for index, (component_name, (cluster_name, service_name)) in enumerate(sorted(service_refs.items())):
        dimensions = [
            {"Name": "ClusterName", "Value": cluster_name},
            {"Name": "ServiceName", "Value": service_name},
        ]
        cpu_id = f"c{index}"
        mem_id = f"m{index}"
        queries.append(
            {
                "Id": cpu_id,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/ECS",
                        "MetricName": "CPUUtilization",
                        "Dimensions": dimensions,
                    },
                    "Period": 60,
                    "Stat": "Average",
                },
            }
        )
        queries.append(
            {
                "Id": mem_id,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/ECS",
                        "MetricName": "MemoryUtilization",
                        "Dimensions": dimensions,
                    },
                    "Period": 60,
                    "Stat": "Average",
                },
            }
        )
        query_map[cpu_id] = (component_name, "cpu")
        query_map[mem_id] = (component_name, "mem")

    if not queries:
        return

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=12)
    try:
        resp = cloudwatch_client.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start_time,
            EndTime=end_time,
        )
    except Exception:
        logger.exception("Failed to resolve CloudWatch service metrics")
        return

    for result in resp.get("MetricDataResults", []):
        metric_info = query_map.get(result.get("Id"))
        if not metric_info:
            continue
        component_name, metric_type = metric_info
        component = components.get(component_name)
        if component is None:
            continue
        values = result.get("Values", [])
        if not values:
            continue
        if metric_type == "cpu":
            component["cpu_1m"] = round(values[0])
            component["cpu_10m"] = round(sum(values) / len(values))
        else:
            component["mem_pct"] = round(values[0])


def _task_definition_image(
    *,
    ecs_client,
    task_definition_arn: str,
    container_name: Any,
    task_definition_cache: dict[str, dict[str, Any]],
) -> str | None:
    task_definition = task_definition_cache.get(task_definition_arn)
    if task_definition is None:
        resp = ecs_client.describe_task_definition(taskDefinition=task_definition_arn)
        task_definition = resp["taskDefinition"]
        task_definition_cache[task_definition_arn] = task_definition

    definitions = task_definition.get("containerDefinitions", [])
    container_name_str = str(container_name or "").strip()
    for definition in definitions:
        if definition.get("name") == container_name_str:
            return definition.get("image")
    if len(definitions) == 1:
        return definitions[0].get("image")
    return None


def _primary_summary_component(components: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for component_name in _PRIMARY_COMPONENTS:
        component = components.get(component_name)
        if component:
            return component
    return {}


def _component_manifest(manifest: dict[str, Any], component_name: str) -> dict[str, Any]:
    component = manifest.get(component_name)
    if isinstance(component, dict):
        return dict(component)
    return {}


def _outputs_by_key(stack: dict[str, Any]) -> dict[str, Any]:
    return {
        output["OutputKey"]: output["OutputValue"]
        for output in stack.get("Outputs", [])
        if "OutputKey" in output and "OutputValue" in output
    }


def _tags_by_key(stack: dict[str, Any]) -> dict[str, Any]:
    return {
        tag["Key"]: tag["Value"]
        for tag in stack.get("Tags", [])
        if "Key" in tag and "Value" in tag
    }


def _service_identity_from_arn(service_arn: str) -> tuple[str, str]:
    try:
        resource = service_arn.split("service/", 1)[1]
    except IndexError as exc:
        raise ValueError(f"Unrecognized ECS service ARN: {service_arn}") from exc

    parts = [part for part in resource.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Missing cluster or service name in ECS service ARN: {service_arn}")
    return parts[-2], parts[-1]
