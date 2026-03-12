"""Shared Discord setup checks used by dashboard and CLI flows."""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def discord_secret_status(
    name: str,
    region: str,
    *,
    session: boto3.Session | None = None,
) -> tuple[bool | None, str | None]:
    """Return whether the Discord token secret exists and contains an access token."""
    secret_id = f"cogent/{name}/discord"
    sm = session.client("secretsmanager", region_name=region) if session else boto3.client(
        "secretsmanager",
        region_name=region,
    )
    try:
        resp = sm.get_secret_value(SecretId=secret_id)
        data = json.loads(resp.get("SecretString", "{}"))
        return bool(data.get("access_token")), None
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            return False, None
        logger.warning("Discord secret check failed for %s: %s", name, code or exc)
        return None, code or type(exc).__name__
    except Exception as exc:
        logger.warning("Discord secret check failed for %s: %s", name, exc)
        return None, type(exc).__name__


def discord_service_status(
    name: str,
    region: str,
    *,
    session: boto3.Session | None = None,
) -> tuple[dict[str, int | str | bool | None], str | None]:
    """Return ECS status for the Discord bridge service."""
    safe_name = name.replace(".", "-")
    service_name = f"cogent-{safe_name}-discord"
    ecs = session.client("ecs", region_name=region) if session else boto3.client(
        "ecs",
        region_name=region,
    )
    try:
        resp = ecs.describe_services(cluster="cogent-polis", services=[service_name])
        services = resp.get("services", [])
        if not services:
            return {
                "bridge_service_exists": False,
                "bridge_status": None,
                "bridge_desired_count": None,
                "bridge_running_count": None,
                "bridge_pending_count": None,
            }, None
        svc = services[0]
        return {
            "bridge_service_exists": True,
            "bridge_status": svc.get("status"),
            "bridge_desired_count": svc.get("desiredCount"),
            "bridge_running_count": svc.get("runningCount"),
            "bridge_pending_count": svc.get("pendingCount"),
        }, None
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        logger.warning("Discord service check failed for %s: %s", name, code or exc)
        return {
            "bridge_service_exists": None,
            "bridge_status": None,
            "bridge_desired_count": None,
            "bridge_running_count": None,
            "bridge_pending_count": None,
        }, code or type(exc).__name__
    except Exception as exc:
        logger.warning("Discord service check failed for %s: %s", name, exc)
        return {
            "bridge_service_exists": None,
            "bridge_status": None,
            "bridge_desired_count": None,
            "bridge_running_count": None,
            "bridge_pending_count": None,
        }, type(exc).__name__
