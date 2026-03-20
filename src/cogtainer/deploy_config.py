"""Deploy configuration: organization, domain, cogent roster."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

_CONFIG_PATH = Path.home() / ".cogos" / "config.yml"
_config_cache: dict[str, Any] | None = None


def _load_deploy_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if _CONFIG_PATH.is_file():
        with open(_CONFIG_PATH) as f:
            result: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        result = {}
    _config_cache = result
    return result


def deploy_config(key: str, default: str) -> str:
    return str(_load_deploy_config().get(key, default))


class CogentMeta(BaseModel):
    description: str = ""
    personality: str | None = None


class ServiceQuotaTarget(BaseModel):
    service_code: str = "bedrock"
    quota_code: str
    quota_name: str
    desired_value: float
    region: str = "us-east-1"


def _default_bedrock_quotas() -> list[ServiceQuotaTarget]:
    """Default Bedrock quota targets for the shared cogtainer account."""
    return [
        ServiceQuotaTarget(
            quota_code="L-59759B4A",
            quota_name="Cross-region model inference tokens per minute for Anthropic Claude Sonnet 4 V1",
            desired_value=1_000_000,
        ),
        ServiceQuotaTarget(
            quota_code="L-559DCC33",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4 V1",
            desired_value=500,
        ),
        ServiceQuotaTarget(
            quota_code="L-CCA5DF70",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Haiku 4.5",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-27989F42",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Opus 4.5",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-11DFF789",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Opus 4.6 V1",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-410BCACA",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Opus 4.6 V1 1M Context Length",
            desired_value=1_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-4A6BFAB1",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-A052927A",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1 1M Context Length",
            desired_value=1_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-00FF3314",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.6",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-47DE5258",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.6 1M Context Length",
            desired_value=1_001,
        ),
    ]


class CogtainerConfig(BaseModel):
    name: str = Field(default_factory=lambda: deploy_config("cogtainer_name", ""))
    organization: str = Field(default_factory=lambda: deploy_config("organization", "Softmax"))
    owner: str = Field(default_factory=lambda: deploy_config("owner", ""))
    domain: str = Field(default_factory=lambda: deploy_config("domain", "softmax-cogents.com"))
    cogents: dict[str, CogentMeta] = {}
    bedrock_quotas: list[ServiceQuotaTarget] = Field(default_factory=_default_bedrock_quotas)

    def template_vars(self, cogent_name: str) -> dict[str, str]:
        """Return template variables for a cogent."""
        cogent = self.cogents.get(cogent_name, CogentMeta())
        return {
            "cogent_name": cogent_name,
            "cogtainer_name": self.name,
            "organization": self.organization,
            "owner": self.owner,
            "description": cogent.description,
            "personality": cogent.personality or "",
        }
