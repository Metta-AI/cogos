"""Helpers for canonical cogent status identity and display."""

from __future__ import annotations

from typing import Any


def expected_stack_name(cogent_name: str) -> str:
    """Return the expected brain stack name for a cogent."""
    return f"cogent-{cogent_name.replace('.', '-')}-brain"


def safe_name_from_stack_name(stack_name: str) -> str:
    """Extract the safe cogent name from a brain stack name."""
    name = stack_name.removeprefix("cogent-")
    if name.endswith("-brain"):
        name = name[: -len("-brain")]
    return name


def status_stack_name(item: dict[str, Any]) -> str:
    """Resolve the brain stack name for a status row."""
    stack_name = str(item.get("stack_name") or "").strip()
    if stack_name:
        return stack_name

    cogent_name = str(item.get("cogent_name") or "").strip()
    if cogent_name.endswith("-brain"):
        return f"cogent-{cogent_name}"
    return expected_stack_name(cogent_name)


def coalesce_status_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate status rows that refer to the same underlying stack."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(status_stack_name(item), []).append(item)

    merged: list[dict[str, Any]] = []
    for stack_name, group in groups.items():
        identity_item = next((item for item in group if record_type(item) == "identity"), None)
        merged_item = dict(identity_item or max(group, key=lambda item: _int_value(item.get("updated_at"))))
        merged_item["stack_name"] = stack_name
        merged_item["record_type"] = record_type(identity_item or merged_item)
        merged_item["cogent_name"] = (
            identity_item.get("cogent_name")
            if identity_item and identity_item.get("cogent_name")
            else merged_item.get("cogent_name") or safe_name_from_stack_name(stack_name)
        )

        for item in group:
            status = item.get("stack_status")
            if status and status != "REGISTERED":
                merged_item["stack_status"] = status
            if item.get("image_tag") not in (None, "", "-"):
                merged_item["image_tag"] = item["image_tag"]
            for key in ("running_count", "desired_count", "cpu_1m", "cpu_10m", "mem_pct", "updated_at"):
                if _int_value(item.get(key)) > _int_value(merged_item.get(key)):
                    merged_item[key] = item[key]
            if item.get("channels"):
                channels = dict(merged_item.get("channels") or {})
                channels.update(item["channels"])
                merged_item["channels"] = channels
            for key in ("domain", "certificate_arn"):
                if item.get(key):
                    merged_item[key] = item[key]

        merged.append(merged_item)

    return merged


def record_type(item: dict[str, Any]) -> str:
    """Return the explicit status row type.

    `identity` rows are created by `polis cogents create`.
    `runtime` rows are written by the watcher from CloudFormation/ECS state.
    """
    kind = str(item.get("record_type") or "").strip()
    if kind:
        return kind

    # Backward-compatible interpretation for older REGISTERED rows created
    # before `record_type` existed.
    if item.get("stack_status") == "REGISTERED" and item.get("domain") and item.get("certificate_arn"):
        return "identity"
    return "runtime"


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
