"""Tests for supervisor cog configuration — approval support."""
from __future__ import annotations

from pathlib import Path

from cogos.cog.cog import Cog

SUPERVISOR_DIR = Path(__file__).resolve().parents[2] / "images" / "cogos" / "cogos" / "supervisor"


class TestSupervisorCogApproval:
    def test_proposals_not_a_handler(self):
        """supervisor:proposals is storage, not a wakeup handler."""
        cog = Cog(SUPERVISOR_DIR)
        assert "supervisor:proposals" not in cog.config.handlers

    def test_handlers_include_help(self):
        """Supervisor still subscribes to supervisor:help."""
        cog = Cog(SUPERVISOR_DIR)
        assert "supervisor:help" in cog.config.handlers

    def test_handlers_include_reaction(self):
        """Supervisor subscribes to io:discord:reaction."""
        cog = Cog(SUPERVISOR_DIR)
        assert "io:discord:reaction" in cog.config.handlers
