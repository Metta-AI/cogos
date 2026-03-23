"""Helpers for per-checkout local-development defaults."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_DATA_SUBDIR = Path(".local") / "cogos"
_DASHBOARD_PORT_SPAN = 5000
_DASHBOARD_BE_BASE = 23000
_DASHBOARD_FE_BASE = 28000


def repo_root() -> Path:
    """Return the checkout root for the current source tree."""
    return _REPO_ROOT


def default_local_data_dir(*, repo_root: Path | None = None) -> Path:
    """Return the default local CogOS data directory for this checkout."""
    root = (repo_root or _REPO_ROOT).resolve()
    return root / _LOCAL_DATA_SUBDIR


def default_dashboard_ports(*, repo_root: Path | None = None) -> tuple[int, int]:
    """Return a stable backend/frontend port pair for this checkout."""
    root = (repo_root or _REPO_ROOT).resolve()
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
    slot = int(digest[:8], 16) % _DASHBOARD_PORT_SPAN
    return _DASHBOARD_BE_BASE + slot, _DASHBOARD_FE_BASE + slot


def apply_local_checkout_env(
    env: MutableMapping[str, str] | None = None,
    *,
    repo_root: Path | None = None,
) -> MutableMapping[str, str]:
    """Populate local-only env defaults without overwriting explicit overrides."""
    target = env if env is not None else os.environ
    target["USE_LOCAL_DB"] = "1"
    return target


def resolve_dashboard_ports(
    *,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> tuple[int, int]:
    """Resolve dashboard ports from env, repo .env, or checkout-derived defaults."""
    root = (repo_root or _REPO_ROOT).resolve()
    current_env = env if env is not None else os.environ
    env_file_values = _read_repo_env(root / ".env")
    default_be, default_fe = default_dashboard_ports(repo_root=root)

    be_raw = current_env.get("DASHBOARD_BE_PORT") or env_file_values.get("DASHBOARD_BE_PORT")
    fe_raw = current_env.get("DASHBOARD_FE_PORT") or env_file_values.get("DASHBOARD_FE_PORT")

    return (
        int(be_raw) if be_raw else default_be,
        int(fe_raw) if fe_raw else default_fe,
    )


def _read_repo_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.split("#", 1)[0].strip()
    return values


def write_repo_env(updates: dict[str, str], *, repo_root: Path | None = None) -> Path:
    """Upsert key=value pairs into the repo-local .env file.

    Preserves comments and unrelated keys. Returns the .env path.
    """
    root = (repo_root or _REPO_ROOT).resolve()
    env_path = root / ".env"

    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    remaining = dict(updates)

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")
    return env_path
