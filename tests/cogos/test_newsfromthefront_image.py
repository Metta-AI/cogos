"""Tests for the newsfromthefront app image loading and wiring."""

from pathlib import Path

from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore
from cogos.image.apply import apply_image
from cogos.image.spec import load_image


def test_cogent_v1_newsfromthefront_cog_declared():
    """The newsfromthefront cog should be declared in the image spec."""
    spec = load_image(Path("images/cogos"))

    cog = next((c for c in spec.cogs if c["name"] == "newsfromthefront"), None)
    assert cog is not None, "newsfromthefront cog not found in spec"
    assert cog["config"] is not None, "config not declared"
    assert cog["entrypoint"] == "main.py"


def test_cogent_v1_newsfromthefront_config_is_daemon():
    """The cog config should be a daemon with proper capabilities."""
    spec = load_image(Path("images/cogos"))

    cog = next(c for c in spec.cogs if c["name"] == "newsfromthefront")
    config = cog["config"]
    assert config["mode"] == "daemon"
    cap_names = [c if isinstance(c, str) else c["name"] for c in config["capabilities"]]
    assert "discord" in cap_names


def test_cogent_v1_newsfromthefront_has_handlers():
    """The cog should subscribe to all NFF channels."""
    spec = load_image(Path("images/cogos"))

    cog = next(c for c in spec.cogs if c["name"] == "newsfromthefront")
    handlers = cog["config"]["handlers"]
    expected_handlers = [
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ]
    for h in expected_handlers:
        assert h in handlers


def test_cogent_v1_newsfromthefront_prompt_files_exist():
    """All child prompt files should be loaded as files in the spec."""
    spec = load_image(Path("images/cogos"))

    expected_files = [
        "mnt/boot/newsfromthefront/main.py",
        "mnt/boot/newsfromthefront/researcher.md",
        "mnt/boot/newsfromthefront/analyst.md",
        "mnt/boot/newsfromthefront/test.md",
        "mnt/boot/newsfromthefront/backfill.md",
    ]
    for key in expected_files:
        assert key in spec.files


def test_cogent_v1_newsfromthefront_whoami_is_app_scoped():
    """The app identity file should not collide with the image-level whoami key."""
    spec = load_image(Path("images/cogos"))

    assert "mnt/boot/whoami/index.md" in spec.files
    assert "mnt/boot/newsfromthefront/whoami/index.md" in spec.files


def test_cogent_v1_newsfromthefront_cog_apply(tmp_path):
    """Cog manifest should be written to FileStore on apply."""
    import json

    spec = load_image(Path("images/cogos"))
    repo = SqliteRepository(str(tmp_path))
    apply_image(spec, repo)

    store = FileStore(repo)

    # Verify manifest is written
    raw = store.get_content("mnt/boot/_boot/cog_manifests.json")
    assert raw is not None
    manifests = json.loads(raw)
    entry = next((e for e in manifests if e["name"] == "newsfromthefront"), None)
    assert entry is not None
    assert entry["config"]["mode"] == "daemon"

    # Content file should be in FileStore
    content = store.get_content("mnt/boot/newsfromthefront/main.py")
    assert content is not None
