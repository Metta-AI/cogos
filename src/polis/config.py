"""Polis configuration: organization, domain, cogent roster."""

from __future__ import annotations

from pydantic import BaseModel


class CogentMeta(BaseModel):
    description: str = ""
    personality: str | None = None


class PolisConfig(BaseModel):
    name: str = "softmax-polis"
    organization: str = "Softmax"
    owner: str = "daveey"
    domain: str = "softmax-cogents.com"
    cogents: dict[str, CogentMeta] = {}

    def template_vars(self, cogent_name: str) -> dict[str, str]:
        """Return template variables for a cogent."""
        cogent = self.cogents.get(cogent_name, CogentMeta())
        return {
            "cogent_name": cogent_name,
            "polis_name": self.name,
            "organization": self.organization,
            "owner": self.owner,
            "description": cogent.description,
            "personality": cogent.personality or "",
        }
