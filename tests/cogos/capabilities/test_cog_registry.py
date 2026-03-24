"""Tests for CogRegistryCapability."""
from __future__ import annotations

from uuid import uuid4

import pytest

from cogos.capabilities.cog_registry import CogRegistryCapability, CogProxy
from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(str(tmp_path))


@pytest.fixture
def pid():
    return uuid4()


def _populate_worker_cog(repo):
    """Create worker cog files in FileStore."""
    fs = FileStore(repo)
    fs.create("cogos/worker/main.md", "# Worker\n\nYou are a worker. Complete the task below.\n")
    fs.create("cogos/worker/make_coglet.py", (
        "from cogos.cog.cog import CogConfig\n"
        "from cogos.cog.runtime import CogletManifest\n"
        "\n"
        "def make_coglet(reason, cog_dir=None):\n"
        "    template = ''\n"
        "    if cog_dir:\n"
        "        template = (cog_dir / 'main.md').read_text()\n"
        "    content = template + '\\n\\n## Task\\n\\n' + reason\n"
        "    manifest = CogletManifest(\n"
        "        name='worker-task',\n"
        "        config=CogConfig(mode='one_shot'),\n"
        "        content=content,\n"
        "        entrypoint='main.md',\n"
        "    )\n"
        "    caps = ['channels']\n"
        "    if 'github' in reason.lower():\n"
        "        caps.append('github')\n"
        "    return manifest, caps\n"
    ))


class TestCogRegistry:
    def test_get_or_make_cog(self, repo, pid):
        _populate_worker_cog(repo)
        cap = CogRegistryCapability(repo, pid)
        cog = cap.get_or_make_cog("cogos/worker")
        assert cog.name == "worker"
        assert isinstance(cog, CogProxy)

    def test_caches_cog(self, repo, pid):
        _populate_worker_cog(repo)
        cap = CogRegistryCapability(repo, pid)
        cog1 = cap.get_or_make_cog("cogos/worker")
        cog2 = cap.get_or_make_cog("cogos/worker")
        assert cog1 is cog2

    def test_make_coglet_returns_manifest_and_caps(self, repo, pid):
        _populate_worker_cog(repo)
        cap = CogRegistryCapability(repo, pid)
        cog = cap.get_or_make_cog("cogos/worker")
        manifest, caps = cog.make_coglet("create a github issue")
        assert manifest.name == "worker-task"
        assert "## Task" in manifest.content
        assert "github issue" in manifest.content
        assert "github" in caps

    def test_make_coglet_includes_template(self, repo, pid):
        _populate_worker_cog(repo)
        cap = CogRegistryCapability(repo, pid)
        cog = cap.get_or_make_cog("cogos/worker")
        manifest, _ = cog.make_coglet("do something")
        assert "Worker" in manifest.content
        assert "do something" in manifest.content

    def test_make_coglet_without_file_raises(self, repo, pid):
        fs = FileStore(repo)
        fs.create("cogos/nocoglet/main.md", "# No factory")
        cap = CogRegistryCapability(repo, pid)
        cog = cap.get_or_make_cog("cogos/nocoglet")
        with pytest.raises(FileNotFoundError, match="make_coglet"):
            cog.make_coglet("some task")
