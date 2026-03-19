"""Structural invariant tests for the Discord handler prompt (main.md)."""

from pathlib import Path

import pytest


def _read_main():
    return Path(__file__).parent.joinpath("main.md").read_text()


class TestRequiredSections:
    """Every required top-level section must be present."""

    @pytest.mark.parametrize(
        "section",
        ["## Flow", "## Responding", "## Escalation", "## Guidelines"],
    )
    def test_section_exists(self, section):
        text = _read_main()
        assert section in text, f"Missing required section: {section}"


class TestRequiredCapabilities:
    """The prompt must reference each capability the handler depends on."""

    @pytest.mark.parametrize("cap", ["discord", "channels", "dir"])
    def test_capability_referenced(self, cap):
        text = _read_main()
        assert (
            f"`{cap}`" in text or f"`{cap}." in text
        ), f"Missing reference to capability: {cap}"


class TestWaterlineDedup:
    """The handler must contain a waterline-based deduplication pattern."""

    def test_waterline_dedup_pattern(self):
        text = _read_main()
        assert "waterline" in text.lower(), "Missing waterline dedup pattern"
        assert "seen" in text, "Missing 'seen' list in waterline logic"


class TestEscalation:
    """Escalation must route through supervisor:help."""

    def test_supervisor_help_channel(self):
        text = _read_main()
        assert "supervisor:help" in text, "Missing escalation to supervisor:help"


class TestSendIncludesReplyTo:
    """Every discord.send call must include reply_to."""

    def test_send_calls_include_reply_to(self):
        text = _read_main()
        lines = text.splitlines()
        for line in lines:
            if "discord.send(" in line:
                assert "reply_to" in line, (
                    f"discord.send() missing reply_to: {line.strip()}"
                )


class TestMinimumLength:
    """The prompt must exceed a minimum length to be meaningful."""

    def test_prompt_exceeds_minimum_length(self):
        text = _read_main()
        assert len(text) >= 500, (
            f"Prompt too short ({len(text)} chars); expected at least 500"
        )
