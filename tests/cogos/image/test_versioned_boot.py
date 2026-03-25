"""Integration test: boot with version manifest."""
import json
from pathlib import Path

from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore
from cogos.image.apply import apply_image
from cogos.image.spec import load_image
from cogos.image.versions import (
    VersionManifest,
    load_defaults,
    resolve_versions,
    write_versions_to_filestore,
)


def test_boot_writes_versions(tmp_path):
    """Full boot writes versions.json to FileStore."""
    repo = SqliteRepository(tmp_path / "data.json")

    # Load real image
    repo_root = Path(__file__).resolve().parents[3]
    image_dir = repo_root / "images" / "cogos"
    assert image_dir.is_dir(), f"Image not found: {image_dir}"

    # Resolve versions (all local for test)
    defaults = load_defaults(image_dir)
    components = resolve_versions(defaults, {})

    # Write versions
    manifest = VersionManifest(epoch=repo.reboot_epoch, cogent_name="test", components=components)
    fs = FileStore(repo)
    write_versions_to_filestore(manifest, fs)

    # Boot image
    spec = load_image(image_dir)
    counts = apply_image(spec, repo)
    assert counts["processes"] > 0

    # Verify versions.json is in FileStore
    content = fs.get_content("mnt/boot/versions.json")
    assert content is not None
    data = json.loads(content)
    assert data["cogent_name"] == "test"
    assert "executor" in data["components"]
