"""Tests for the newsfromthefront app image loading and wiring."""

from pathlib import Path

from cogos.cog import load_cog_meta, load_coglet_meta
from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore
from cogos.image.apply import apply_image
from cogos.image.spec import load_image


def test_cogent_v1_newsfromthefront_cog_declared():
    """The newsfromthefront cog should be declared in the image spec."""
    spec = load_image(Path("images/cogent-v1"))

    cog = next((c for c in spec.cogs if c["name"] == "newsfromthefront"), None)
    assert cog is not None, "newsfromthefront cog not found in spec"
    assert cog["default_coglet"] is not None, "default_coglet not declared"


def test_cogent_v1_newsfromthefront_default_coglet_is_daemon():
    """The default coglet should be a daemon with cog + coglet_runtime capabilities."""
    spec = load_image(Path("images/cogent-v1"))

    cog = next(c for c in spec.cogs if c["name"] == "newsfromthefront")
    default = cog["default_coglet"]
    assert default["mode"] == "daemon"
    assert default["entrypoint"] == "newsfromthefront.py"
    cap_names = [c if isinstance(c, str) else c["name"] for c in default["capabilities"]]
    assert "cog" in cap_names
    assert "coglet_runtime" in cap_names
    assert "discord" in cap_names


def test_cogent_v1_newsfromthefront_default_coglet_has_handlers():
    """The default coglet should subscribe to all NFF channels."""
    spec = load_image(Path("images/cogent-v1"))

    cog = next(c for c in spec.cogs if c["name"] == "newsfromthefront")
    default = cog["default_coglet"]
    expected_handlers = [
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ]
    for h in expected_handlers:
        assert h in default["handlers"]


def test_cogent_v1_newsfromthefront_prompt_files_exist():
    """All child prompt files should be loaded as files in the spec."""
    spec = load_image(Path("images/cogent-v1"))

    expected_files = [
        "apps/newsfromthefront/newsfromthefront.py",
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


def test_cogent_v1_newsfromthefront_cog_apply(tmp_path):
    """Cog should be persisted to the repo on apply with default coglet + process."""
    spec = load_image(Path("images/cogent-v1"))
    repo = LocalRepository(str(tmp_path))
    apply_image(spec, repo)

    store = FileStore(repo)

    # Cog meta should exist
    cog_meta = load_cog_meta(store, "newsfromthefront")
    assert cog_meta is not None
    assert cog_meta.name == "newsfromthefront"

    # Default coglet should exist
    coglet_meta = load_coglet_meta(store, "newsfromthefront", "newsfromthefront")
    assert coglet_meta is not None
    assert coglet_meta.entrypoint == "newsfromthefront.py"
    assert coglet_meta.mode == "daemon"

    # Process creation is deferred to init.py — verify boot manifest instead
    raw = store.get_content("_boot/cog_processes.json")
    assert raw is not None
    import json
    manifest = json.loads(raw)
    entry = next((e for e in manifest if e["name"] == "newsfromthefront"), None)
    assert entry is not None
    assert entry["mode"] == "daemon"
