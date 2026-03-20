"""Naming helpers — centralizes all AWS resource name prefixes."""

from __future__ import annotations

RESOURCE_PREFIX = "cogent"


def _join(*parts: str) -> str:
    return "-".join(p for p in parts if p)


def safe(cogent_name: str) -> str:
    return cogent_name.replace(".", "-")


def stack_name(cogent_name: str) -> str:
    return f"{RESOURCE_PREFIX}-{safe(cogent_name)}-cogtainer"


def cogtainer_stack_name() -> str:
    return "cogtainer"


def secrets_stack_name() -> str:
    return f"{RESOURCE_PREFIX}-secrets"


def lambda_name(safe_name: str, fn_type: str) -> str:
    return _join(RESOURCE_PREFIX, safe_name, fn_type)


def bucket_name(cogent_name: str) -> str:
    return f"{RESOURCE_PREFIX}-{safe(cogent_name)}-cogtainer-sessions"


def cogtainer_bucket_name(suffix: str) -> str:
    return _join("cogtainer", suffix)


def queue_name(safe_name: str, suffix: str) -> str:
    return _join(RESOURCE_PREFIX, safe_name, suffix)


def event_bus_name(safe_name: str) -> str:
    return f"{RESOURCE_PREFIX}-{safe_name}"


def shared_event_bus_name() -> str:
    return "cogtainer-events"


def rule_name(safe_name: str, suffix: str) -> str:
    return _join(RESOURCE_PREFIX, safe_name, suffix)


def alarm_name(safe_name: str, suffix: str) -> str:
    return _join(RESOURCE_PREFIX, safe_name, suffix)


def ecs_family(safe_name: str, suffix: str) -> str:
    return _join(RESOURCE_PREFIX, safe_name, suffix)


def ecs_service_name(safe_name: str, suffix: str) -> str:
    return _join(RESOURCE_PREFIX, safe_name, suffix)


def log_group_name(safe_name: str, suffix: str) -> str:
    return f"/ecs/{_join(RESOURCE_PREFIX, safe_name, suffix)}"


def cluster_name() -> str:
    return "cogtainer"


def iam_role_name(suffix: str) -> str:
    return f"{RESOURCE_PREFIX}-{suffix}"


def ecr_repo_name() -> str:
    return RESOURCE_PREFIX


def table_name(suffix: str) -> str:
    return f"{RESOURCE_PREFIX}-{suffix}"


def db_name() -> str:
    return RESOURCE_PREFIX
