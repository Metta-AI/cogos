"""Tests for directory-based Cog class."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cogos.cog.cog import Cog, CogConfig, CogletRef, resolve_cog_paths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cog_dir(tmp_path: Path) -> Path:
    """Create a minimal cog directory with main.py."""
    d = tmp_path / "my_cog"
    d.mkdir()
    (d / "main.py").write_text("print('hello')")
    return d


@pytest.fixture()
def cog_dir_md(tmp_path: Path) -> Path:
    """Cog directory with main.md instead of main.py."""
    d = tmp_path / "md_cog"
    d.mkdir()
    (d / "main.md").write_text("# prompt\nDo something.")
    return d


@pytest.fixture()
def cog_dir_with_config(tmp_path: Path) -> Path:
    """Cog directory with a cog.py config file."""
    d = tmp_path / "configured_cog"
    d.mkdir()
    (d / "main.py").write_text("print('configured')")
    (d / "cog.py").write_text(textwrap.dedent("""\
        from cogos.cog.cog import CogConfig

        config = CogConfig(
            mode="persistent",
            priority=5.0,
            executor="shell",
            model="claude-3",
            capabilities=["web", "files"],
            handlers=["on_message"],
            idle_timeout_ms=30000,
        )
    """))
    return d


@pytest.fixture()
def cog_dir_with_coglets(tmp_path: Path) -> Path:
    """Cog directory with child coglet subdirectories."""
    d = tmp_path / "parent_cog"
    d.mkdir()
    (d / "main.py").write_text("print('parent')")

    # coglet with main.py
    child1 = d / "child_a"
    child1.mkdir()
    (child1 / "main.py").write_text("print('child a')")

    # coglet with main.md
    child2 = d / "child_b"
    child2.mkdir()
    (child2 / "main.md").write_text("# child b prompt")

    # coglet with its own cog.py
    child3 = d / "child_c"
    child3.mkdir()
    (child3 / "main.py").write_text("print('child c')")
    (child3 / "cog.py").write_text(textwrap.dedent("""\
        from cogos.cog.cog import CogConfig
        config = CogConfig(priority=10.0, mode="persistent")
    """))

    # directory without main.* should NOT be a coglet
    not_coglet = d / "data"
    not_coglet.mkdir()
    (not_coglet / "stuff.txt").write_text("not a coglet")

    return d


# ---------------------------------------------------------------------------
# CogConfig tests
# ---------------------------------------------------------------------------

class TestCogConfig:
    def test_defaults(self):
        c = CogConfig()
        assert c.mode == "one_shot"
        assert c.priority == 0.0
        assert c.executor == "llm"
        assert c.model is None
        assert c.required_tags == []
        assert c.capabilities == []
        assert c.handlers == []
        assert c.idle_timeout_ms is None

    def test_custom_values(self):
        c = CogConfig(mode="persistent", priority=3.0, model="gpt-4")
        assert c.mode == "persistent"
        assert c.priority == 3.0
        assert c.model == "gpt-4"


# ---------------------------------------------------------------------------
# Cog loading tests
# ---------------------------------------------------------------------------

class TestCogLoading:
    def test_load_minimal_cog(self, cog_dir: Path):
        cog = Cog(cog_dir)
        assert cog.name == "my_cog"
        assert cog.path == cog_dir
        assert cog.main_entrypoint == "main.py"
        assert cog.main_content == "print('hello')"
        # default config
        assert cog.config.mode == "one_shot"

    def test_load_md_cog(self, cog_dir_md: Path):
        cog = Cog(cog_dir_md)
        assert cog.name == "md_cog"
        assert cog.main_entrypoint == "main.md"
        assert "Do something." in cog.main_content

    def test_load_with_config(self, cog_dir_with_config: Path):
        cog = Cog(cog_dir_with_config)
        assert cog.config.mode == "persistent"
        assert cog.config.priority == 5.0
        assert cog.config.executor == "shell"
        assert cog.config.model == "claude-3"
        assert cog.config.capabilities == ["web", "files"]
        assert cog.config.handlers == ["on_message"]
        assert cog.config.idle_timeout_ms == 30000

    def test_no_main_raises(self, tmp_path: Path):
        d = tmp_path / "bad_cog"
        d.mkdir()
        with pytest.raises(FileNotFoundError):
            Cog(d)

    def test_path_does_not_exist_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            Cog(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# Coglet tests
# ---------------------------------------------------------------------------

class TestCoglets:
    def test_coglet_names(self, cog_dir_with_coglets: Path):
        cog = Cog(cog_dir_with_coglets)
        names = sorted(cog.coglets)
        assert names == ["child_a", "child_b", "child_c"]
        # "data" dir should not be included
        assert "data" not in names

    def test_get_coglet(self, cog_dir_with_coglets: Path):
        cog = Cog(cog_dir_with_coglets)
        ref = cog.get_coglet("child_a")
        assert isinstance(ref, CogletRef)
        assert ref.name == "child_a"
        assert ref.entrypoint == "main.py"
        assert ref.content == "print('child a')"
        assert ref.config.mode == "one_shot"  # default

    def test_get_coglet_md(self, cog_dir_with_coglets: Path):
        cog = Cog(cog_dir_with_coglets)
        ref = cog.get_coglet("child_b")
        assert ref.entrypoint == "main.md"
        assert "child b prompt" in ref.content

    def test_get_coglet_with_config(self, cog_dir_with_coglets: Path):
        cog = Cog(cog_dir_with_coglets)
        ref = cog.get_coglet("child_c")
        assert ref.config.priority == 10.0
        assert ref.config.mode == "persistent"

    def test_get_coglet_not_found(self, cog_dir_with_coglets: Path):
        cog = Cog(cog_dir_with_coglets)
        with pytest.raises(FileNotFoundError):
            cog.get_coglet("nonexistent")

    def test_no_coglets(self, cog_dir: Path):
        cog = Cog(cog_dir)
        assert cog.coglets == []


# ---------------------------------------------------------------------------
# resolve_cog_paths tests
# ---------------------------------------------------------------------------

class TestResolveCogPaths:
    def test_resolve_exact(self, cog_dir_with_coglets: Path):
        paths = resolve_cog_paths(
            [str(cog_dir_with_coglets)], base_dir=cog_dir_with_coglets.parent
        )
        assert len(paths) == 1
        assert paths[0] == cog_dir_with_coglets

    def test_resolve_glob(self, tmp_path: Path):
        # Create multiple cogs
        for name in ["cog_a", "cog_b", "not_a_cog"]:
            d = tmp_path / name
            d.mkdir()
            if name != "not_a_cog":
                (d / "main.py").write_text("pass")
            else:
                (d / "readme.txt").write_text("nope")

        paths = resolve_cog_paths(["cog_*"], base_dir=tmp_path)
        names = sorted(p.name for p in paths)
        assert names == ["cog_a", "cog_b"]

    def test_resolve_glob_star(self, tmp_path: Path):
        for name in ["alpha", "beta"]:
            d = tmp_path / name
            d.mkdir()
            (d / "main.md").write_text("prompt")

        paths = resolve_cog_paths(["*"], base_dir=tmp_path)
        assert len(paths) == 2

    def test_resolve_empty(self, tmp_path: Path):
        paths = resolve_cog_paths(["nothing_*"], base_dir=tmp_path)
        assert paths == []

    def test_resolve_relative_to_base(self, tmp_path: Path):
        d = tmp_path / "sub" / "my_cog"
        d.mkdir(parents=True)
        (d / "main.py").write_text("pass")

        paths = resolve_cog_paths(["sub/*"], base_dir=tmp_path)
        assert len(paths) == 1
        assert paths[0] == d
