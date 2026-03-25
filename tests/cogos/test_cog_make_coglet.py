"""Tests for Cog.make_coglet() interface."""
import pytest

from cogos.cog.cog import Cog


def _create_cog_with_make_coglet(tmp_path):
    cog_dir = tmp_path / "worker"
    cog_dir.mkdir()
    (cog_dir / "main.md").write_text("# Worker template\nDo work.\n")
    (cog_dir / "cog.py").write_text(
        "from cogos.cog.cog import CogConfig\nconfig = CogConfig(mode='one_shot')\n"
    )
    (cog_dir / "make_coglet.py").write_text('''
from cogos.cog.cog import CogConfig
from cogos.cog.runtime import CogletManifest

def make_coglet(reason, cog_dir=None):
    template = (cog_dir / "main.md").read_text() if cog_dir else ""
    content = template + "\\n## Task\\n\\n" + reason
    manifest = CogletManifest(
        name="worker-task",
        config=CogConfig(mode="one_shot"),
        content=content,
        entrypoint="main.md",
    )
    caps = ["discord", "channels"]
    if "github" in reason.lower():
        caps.append("github")
    return manifest, caps
''')
    return cog_dir


class TestCogMakeCoglet:
    def test_make_coglet_returns_manifest_and_caps(self, tmp_path):
        cog_dir = _create_cog_with_make_coglet(tmp_path)
        cog = Cog(cog_dir)
        manifest, caps = cog.make_coglet("create a github issue")
        assert manifest.name == "worker-task"
        assert "## Task" in manifest.content
        assert "github issue" in manifest.content
        assert "github" in caps
        assert "discord" in caps

    def test_make_coglet_without_make_py_raises(self, tmp_path):
        cog_dir = tmp_path / "nocoglet"
        cog_dir.mkdir()
        (cog_dir / "main.md").write_text("# No factory")
        (cog_dir / "cog.py").write_text(
            "from cogos.cog.cog import CogConfig\nconfig = CogConfig()\n"
        )
        cog = Cog(cog_dir)
        with pytest.raises(FileNotFoundError, match="make_coglet"):
            cog.make_coglet("some task")

    def test_make_coglet_includes_template(self, tmp_path):
        cog_dir = _create_cog_with_make_coglet(tmp_path)
        cog = Cog(cog_dir)
        manifest, _ = cog.make_coglet("do something")
        assert "Worker template" in manifest.content
        assert "do something" in manifest.content
