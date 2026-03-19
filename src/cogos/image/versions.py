"""Version manifest for CogOS boot."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KNOWN_COMPONENTS = frozenset({
    "executor", "dashboard", "dashboard_frontend",
    "discord_bridge", "lambda", "cogos",
})


@dataclass
class VersionManifest:
    epoch: int
    cogent_name: str
    components: dict[str, str]
    booted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps({
            "epoch": self.epoch,
            "cogent_name": self.cogent_name,
            "booted_at": self.booted_at,
            "components": self.components,
        }, indent=2)

    @classmethod
    def from_json(cls, text: str) -> VersionManifest:
        data = json.loads(text)
        return cls(
            epoch=data["epoch"],
            cogent_name=data["cogent_name"],
            components=data["components"],
            booted_at=data.get("booted_at", ""),
        )


def resolve_versions(
    defaults: dict[str, str],
    overrides: dict[str, str],
) -> dict[str, str]:
    """Merge defaults with CLI overrides. Raises on unknown components."""
    for key in overrides:
        if key not in KNOWN_COMPONENTS:
            raise ValueError(f"Unknown component: {key}")
    return {**defaults, **overrides}
