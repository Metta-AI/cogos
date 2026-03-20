"""Shared Discord setup checks used by dashboard and CLI flows."""

from __future__ import annotations

import json
import logging
from typing import Any

from cogos.capabilities._secrets_helper import fetch_secret

logger = logging.getLogger(__name__)

POLIS_BRIDGE_SERVICE = "cogent-polis-discord"


def discord_secret_status(
    region: str,
    *,
    secrets_provider: object,
    session: Any = None,
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
    session: Any = None,
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
    ecs_client: Any,
) -> tuple[dict[str, int | str | bool | None], str | None]:
    """Return ECS status for the shared polis Discord bridge service."""
    _empty = {
        "bridge_service_exists": None,
        "bridge_status": None,
        "bridge_desired_count": None,
        "bridge_running_count": None,
        "bridge_pending_count": None,
    }
    try:
        resp = ecs_client.describe_services(cluster="cogent-polis", services=[POLIS_BRIDGE_SERVICE])
        services = resp.get("services", [])
        if not services:
            return {**_empty, "bridge_service_exists": False}, None
        svc = services[0]
        return {
            "bridge_service_exists": True,
            "bridge_status": svc.get("status"),
            "bridge_desired_count": svc.get("desiredCount"),
            "bridge_running_count": svc.get("runningCount"),
            "bridge_pending_count": svc.get("pendingCount"),
        }, None
    except Exception as exc:
        error_code = getattr(getattr(exc, "response", {}), "get", lambda *a: "")(
            "Error", {}
        ).get("Code", "") if hasattr(exc, "response") else ""
        label = error_code or type(exc).__name__
        logger.warning("Discord service check failed: %s", label)
        return _empty, label
