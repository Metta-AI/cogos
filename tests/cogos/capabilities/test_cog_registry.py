"""Tests for CogRegistryCapability."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.cog_registry import CogRegistryCapability


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


def _make_cog_dir(tmp_path, name="testcog"):
    cog_dir = tmp_path / name
    cog_dir.mkdir()
    (cog_dir / "main.md").write_text("# Test cog")
    (cog_dir / "cog.py").write_text(
        "from cogos.cog.cog import CogConfig\nconfig = CogConfig()\n"
    )
    return cog_dir


class TestCogRegistry:
    def test_get_or_make_cog(self, tmp_path, repo, pid):
        _make_cog_dir(tmp_path, "worker")
        cap = CogRegistryCapability(repo, pid, base_dir=tmp_path)
        cog = cap.get_or_make_cog("worker")
        assert cog.name == "worker"

    def test_caches_cog(self, tmp_path, repo, pid):
        _make_cog_dir(tmp_path, "worker")
        cap = CogRegistryCapability(repo, pid, base_dir=tmp_path)
        cog1 = cap.get_or_make_cog("worker")
        cog2 = cap.get_or_make_cog("worker")
        assert cog1 is cog2

    def test_not_found_raises(self, tmp_path, repo, pid):
        cap = CogRegistryCapability(repo, pid, base_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            cap.get_or_make_cog("nonexistent")
