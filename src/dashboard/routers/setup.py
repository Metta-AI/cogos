from __future__ import annotations

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter
from pydantic import BaseModel

from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["setup"])


class DiscordSetupResponse(BaseModel):
    secret_path: str
    service_name: str
    cogos_initialized: bool
    cogos_error: str | None = None
    capability_enabled: bool
    dm_handler_enabled: bool
    mention_handler_enabled: bool
    secret_configured: bool | None = None
    secret_check_error: str | None = None
    bridge_service_exists: bool | None = None
    bridge_status: str | None = None
    bridge_desired_count: int | None = None
    bridge_running_count: int | None = None
    bridge_pending_count: int | None = None
    service_check_error: str | None = None
    ready_for_test: bool


def _discord_secret_status(name: str, region: str) -> tuple[bool | None, str | None]:
    secret_id = f"cogent/{name}/discord"
    sm = boto3.client("secretsmanager", region_name=region)
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


def _discord_service_status(name: str, region: str) -> tuple[dict[str, int | str | bool | None], str | None]:
    safe_name = name.replace(".", "-")
    service_name = f"cogent-{safe_name}-discord"
    ecs = boto3.client("ecs", region_name=region)
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


@router.get("/setup/discord", response_model=DiscordSetupResponse)
def discord_setup(name: str) -> DiscordSetupResponse:
    region = os.environ.get("AWS_REGION", "us-east-1")
    safe_name = name.replace(".", "-")

    cogos_initialized = True
    cogos_error = None
    capability_enabled = False
    dm_handler_enabled = False
    mention_handler_enabled = False

    try:
        repo = get_repo()
        caps = repo.list_capabilities()
        capability_enabled = any(cap.name == "discord" and cap.enabled for cap in caps)

        handlers = repo.list_handlers()
        dm_handler_enabled = any(h.enabled and h.event_pattern == "discord:dm" for h in handlers)
        mention_handler_enabled = any(h.enabled and h.event_pattern == "discord:mention" for h in handlers)
    except Exception as exc:
        logger.warning("CogOS setup check failed for %s: %s", name, exc)
        cogos_initialized = False
        cogos_error = type(exc).__name__

    secret_configured, secret_check_error = _discord_secret_status(name, region)
    service_status, service_check_error = _discord_service_status(name, region)

    ready_for_test = (
        cogos_initialized
        and capability_enabled
        and dm_handler_enabled
        and mention_handler_enabled
        and secret_configured is True
        and service_status["bridge_running_count"] is not None
        and int(service_status["bridge_running_count"]) > 0
    )

    return DiscordSetupResponse(
        secret_path=f"cogent/{name}/discord",
        service_name=f"cogent-{safe_name}-discord",
        cogos_initialized=cogos_initialized,
        cogos_error=cogos_error,
        capability_enabled=capability_enabled,
        dm_handler_enabled=dm_handler_enabled,
        mention_handler_enabled=mention_handler_enabled,
        secret_configured=secret_configured,
        secret_check_error=secret_check_error,
        service_check_error=service_check_error,
        ready_for_test=ready_for_test,
        **service_status,
    )
