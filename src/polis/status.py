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
        identity_item = max(group, key=_identity_score)
        merged_item = dict(identity_item)
        merged_item["stack_name"] = stack_name
        merged_item["cogent_name"] = identity_item.get("cogent_name") or safe_name_from_stack_name(stack_name)

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


def _identity_score(item: dict[str, Any]) -> tuple[int, int]:
    """Prefer canonical identity rows over stack-name fallbacks."""
    name = str(item.get("cogent_name") or "")
    score = 0
    if item.get("domain"):
        score += 100
    if item.get("certificate_arn"):
        score += 50
    if "." in name:
        score += 25
    if not name.endswith("-brain"):
        score += 10
    return score, _int_value(item.get("updated_at"))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
