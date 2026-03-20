"""CI deploy configuration for cogtainers — self-contained per-entry config."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class CICogtainerEntry(BaseModel):
    """A single cogtainer deploy target for CI."""

    account_id: str
    region: str = "us-east-1"
    ecr_repo: str
    components: str | list[str] = "all"  # "all" or list like ["lambdas", "dashboard"]
    cogents: list[str] = Field(default_factory=list)
    aws_role: str = ""  # OIDC role ARN


class CIConfig(BaseModel):
    """Top-level cogtainers.ci.yml schema."""

    ci_artifacts_bucket: str = "cogtainer-ci-artifacts"
    cogtainers: dict[str, CICogtainerEntry] = Field(default_factory=dict)

    def deploy_targets(self) -> list[dict]:
        """Return list of deploy target dicts for CI matrix."""
        return [
            {"name": name, **entry.model_dump()}
            for name, entry in sorted(self.cogtainers.items())
        ]


def load_ci_config(path: Path | None = None) -> CIConfig:
    """Load from cogtainers.ci.yml (default: repo root)."""
    if path is None:
        # Walk up from this file to find repo root
        candidate = Path(__file__).resolve().parent.parent.parent / "cogtainers.ci.yml"
        if candidate.is_file():
            path = candidate
        else:
            path = Path("cogtainers.ci.yml")

    if not path.is_file():
        return CIConfig()

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        return CIConfig()

    return CIConfig.model_validate(data)
