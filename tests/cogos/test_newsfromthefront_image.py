"""Tests for the newsfromthefront app image loading and wiring."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_newsfromthefront_root_process():
    """The root orchestrator should be registered with all handlers."""
    spec = load_image(Path("images/cogent-v1"))

    process = next(p for p in spec.processes if p["name"] == "newsfromthefront")
    assert process["mode"] == "daemon"
    assert process["content"] == "@{apps/newsfromthefront/newsfromthefront.md}"
    assert "procs" in process["capabilities"]
    assert "discord" in process["capabilities"]

    expected_handlers = [
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ]
    for h in expected_handlers:
        assert h in process["handlers"]


def test_cogent_v1_newsfromthefront_prompt_files_exist():
    """All child prompt files should be loaded as files in the spec."""
    spec = load_image(Path("images/cogent-v1"))

    expected_files = [
        "apps/newsfromthefront/newsfromthefront.md",
        "apps/newsfromthefront/researcher.md",
        "apps/newsfromthefront/analyst.md",
        "apps/newsfromthefront/test.md",
        "apps/newsfromthefront/backfill.md",
    ]
    for key in expected_files:
        assert key in spec.files


def test_cogent_v1_newsfromthefront_whoami_is_app_scoped():
    """The app identity file should not collide with the image-level whoami key."""
    spec = load_image(Path("images/cogent-v1"))

    assert "whoami/index.md" in spec.files
    assert "apps/newsfromthefront/whoami/index.md" in spec.files
