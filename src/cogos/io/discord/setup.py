"""Shared Discord setup checks used by dashboard and CLI flows."""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from cogos.capabilities._secrets_helper import fetch_secret

logger = logging.getLogger(__name__)

POLIS_BRIDGE_SERVICE = "cogent-polis-discord"


def discord_secret_status(
    region: str,
    *,
    secrets_provider: object,
    session: boto3.Session | None = None,
) -> tuple[bool | None, str | None]:
    """Return whether the shared polis Discord token exists."""
    try:
        raw = fetch_secret("polis/discord", secrets_provider=secrets_provider)
        data = json.loads(raw)
        return bool(data.get("access_token")), None
    except (RuntimeError, KeyError):
        return False, None
    except Exception as exc:
        logger.warning("Discord secret check failed: %s", exc)
        return None, type(exc).__name__


def discord_persona_status(
    name: str,
    region: str,
    *,
    secrets_provider: object,
    session: boto3.Session | None = None,
) -> tuple[dict | None, str | None]:
    """Return persona config for a cogent from the secrets provider."""
    try:
        raw = fetch_secret(f"cogent/{name}/discord", secrets_provider=secrets_provider)
        data = json.loads(raw)
        return data, None
    except (RuntimeError, KeyError):
        return None, None
    except Exception as exc:
        logger.warning("Discord persona check failed for %s: %s", name, exc)
        return None, type(exc).__name__


def discord_service_status(
    region: str,
    *,
    session: boto3.Session | None = None,
) -> tuple[dict[str, int | str | bool | None], str | None]:
    """Return ECS status for the shared polis Discord bridge service."""
    ecs = session.client("ecs", region_name=region) if session else boto3.client(
        "ecs",
        region_name=region,
    )
    try:
        resp = ecs.describe_services(cluster="cogent-polis", services=[POLIS_BRIDGE_SERVICE])
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
        logger.warning("Discord service check failed: %s", code or exc)
        return {
            "bridge_service_exists": None,
            "bridge_status": None,
            "bridge_desired_count": None,
            "bridge_running_count": None,
            "bridge_pending_count": None,
        }, code or type(exc).__name__
    except Exception as exc:
        logger.warning("Discord service check failed: %s", exc)
        return {
            "bridge_service_exists": None,
            "bridge_status": None,
            "bridge_desired_count": None,
            "bridge_running_count": None,
            "bridge_pending_count": None,
        }, type(exc).__name__
