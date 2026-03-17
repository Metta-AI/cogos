"""Tests for the supervisor app image loading and wiring."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_supervisor_loads():
    """The supervisor process should be spawned by init.py at runtime."""
    spec = load_image(Path("images/cogent-v1"))

    # supervisor is spawned at runtime by init.py, not declared as a spec process
    init_content = spec.files.get("cogos/init.py", "")
    assert "supervisor" in init_content

    # The supervisor prompt file should be loaded
    assert "apps/supervisor/supervisor.md" in spec.files


def test_cogent_v1_supervisor_channel():
    """The supervisor:help channel should be defined with schema."""
    spec = load_image(Path("images/cogent-v1"))

    channel_names = {c["name"] for c in spec.channels}
    assert "supervisor:help" in channel_names

    channel = next(c for c in spec.channels if c["name"] == "supervisor:help")
    assert channel.get("schema") == "supervisor-help-request"


def test_cogent_v1_supervisor_schema():
    """The supervisor-help-request schema should be defined."""
    spec = load_image(Path("images/cogent-v1"))

    schema_names = {s["name"] for s in spec.schemas}
    assert "supervisor-help-request" in schema_names


def test_cogent_v1_supervisor_files():
    """The supervisor prompt file should be loaded."""
    spec = load_image(Path("images/cogent-v1"))

    assert "apps/supervisor/supervisor.md" in spec.files
