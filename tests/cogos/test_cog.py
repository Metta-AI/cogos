"""Tests for the directory-based Cog system."""

from __future__ import annotations

from pathlib import Path

from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore


# ---------------------------------------------------------------------------
# Image-level: add_cog + cog manifest
# ---------------------------------------------------------------------------


class TestAddCog:
    def test_add_cog_in_image_spec(self):
        from cogos.image.spec import load_image

        spec = load_image(Path("images/cogos"))
        cog_names = {c["name"] for c in spec.cogs}
        assert "recruiter" in cog_names
        assert "newsfromthefront" in cog_names

    def test_cog_apply_writes_boot_manifest(self, tmp_path):
        import json

        from cogos.image.apply import apply_image
        from cogos.image.spec import load_image

        repo = SqliteRepository(str(tmp_path))
        spec = load_image(Path("images/cogos"))
        apply_image(spec, repo)

        fs = FileStore(repo)
        raw = fs.get_content("mnt/boot/_boot/cog_manifests.json")
        assert raw is not None
        manifest = json.loads(raw)
        names = {e["name"] for e in manifest}
        assert "recruiter" in names
        assert "newsfromthefront" in names
