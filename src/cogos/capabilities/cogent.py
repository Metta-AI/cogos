"""Cogent capability — identity and metadata for the current cogent."""

from __future__ import annotations

import logging
import os

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


class CogentCapability(Capability):
    """Cogent identity — name and metadata.

    Usage:
        cogent.name        # "my-cogent"
        cogent.profile()   # markdown string with identity fields
    """

    def __init__(self, repo, process_id, **kwargs):
        super().__init__(repo, process_id)
        self._name = os.environ.get("COGENT_NAME", "")

    @property
    def name(self) -> str:
        """The cogent's name."""
        return self._name

    def profile(self) -> str:
        """Return identity as a markdown string for prompt injection."""
        return f"- **Cogent Name:** {self._name}\n"

    def __repr__(self) -> str:
        return f"<CogentCapability name={self._name!r}>"
