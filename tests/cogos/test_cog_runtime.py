"""Tests for CogRuntime — spawning cogs and coglets from directory structure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from cogos.cog.cog import Cog, CogConfig, CogletRef
from cogos.cog.runtime import CogRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cog(tmp_path, *, name="mycog", config=None, coglets=None):
    """Create a cog directory with optional coglets."""
    cog_dir = tmp_path / name
    cog_dir.mkdir(parents=True, exist_ok=True)

    # Write main entrypoint
    (cog_dir / "main.md").write_text("You are the main coglet.")

    # Write cog.py config if provided
    if config is not None:
        (cog_dir / "cog.py").write_text(
            "from cogos.cog.cog import CogConfig\n"
            f"config = CogConfig(**{config!r})\n"
        )

    # Create coglet subdirectories
    for cname, cdata in (coglets or {}).items():
        sub = cog_dir / cname
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "main.md").write_text(cdata.get("content", f"I am {cname}."))
        if "config" in cdata:
            (sub / "cog.py").write_text(
                "from cogos.cog.cog import CogConfig\n"
                f"config = CogConfig(**{cdata['config']!r})\n"
            )

    return Cog(cog_dir)


def _mock_cap(name="cap"):
    """Return a MagicMock capability with a .scope() method."""
    cap = MagicMock(name=name)
    scoped = MagicMock(name=f"{name}_scoped")
    cap.scope.return_value = scoped
    return cap


def _mock_procs():
    """Return a MagicMock procs object with .spawn()."""
    procs = MagicMock(name="procs")
    handle = MagicMock(name="process_handle")
    procs.spawn.return_value = handle
    return procs


# ---------------------------------------------------------------------------
# CogRuntime.__init__
# ---------------------------------------------------------------------------

class TestCogRuntimeInit:
    def test_stores_cog_and_caps(self, tmp_path):
        cog = _make_cog(tmp_path)
        caps = {"me": MagicMock(), "discord": MagicMock()}
        rt = CogRuntime(cog, caps)
        assert rt.cog is cog
        assert rt.cap_objects is caps


# ---------------------------------------------------------------------------
# CogRuntime.run_cog
# ---------------------------------------------------------------------------

class TestRunCog:
    def test_spawns_main_coglet(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = CogRuntime(cog, {})

        handle = rt.run_cog(procs)

        procs.spawn.assert_called_once()
        kw = procs.spawn.call_args
        assert kw.kwargs["name"] == "mycog"
        assert kw.kwargs["detached"] is True
        assert handle is procs.spawn.return_value

    def test_passes_content_from_entrypoint(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["content"] == "You are the main coglet."

    def test_passes_mode_from_config(self, tmp_path):
        cog = _make_cog(tmp_path, config={"mode": "daemon"})
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["mode"] == "daemon"

    def test_passes_config_fields(self, tmp_path):
        cog = _make_cog(tmp_path, config={
            "mode": "daemon",
            "priority": 5.0,
            "executor": "llm",
            "model": "gpt-4",
            "runner": "ecs",
            "idle_timeout_ms": 3000,
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["priority"] == 5.0
        assert kw["executor"] == "llm"
        assert kw["model"] == "gpt-4"
        assert kw["runner"] == "ecs"
        assert kw["idle_timeout_ms"] == 3000

    def test_subscribe_from_handlers(self, tmp_path):
        cog = _make_cog(tmp_path, config={"handlers": ["discord.*", "email.*"]})
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["subscribe"] == ["discord.*", "email.*"]

    def test_adds_scoped_dir(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = CogRuntime(cog, {"dir": dir_cap})
        rt.run_cog(procs)

        dir_cap.scope.assert_any_call(prefix="cogs/mycog/")
        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "dir" in caps
        assert caps["dir"] is dir_cap.scope.return_value

    def test_adds_scoped_data(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = CogRuntime(cog, {"dir": dir_cap})
        rt.run_cog(procs)

        # data is also scoped from dir
        calls = dir_cap.scope.call_args_list
        prefixes = [c.kwargs.get("prefix") or c.args[0] for c in calls]
        assert "data/mycog/" in prefixes
        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "data" in caps

    def test_adds_runtime_self(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "runtime" in caps
        assert caps["runtime"] is rt

    def test_string_capabilities_looked_up(self, tmp_path):
        me_cap = MagicMock(name="me")
        discord_cap = MagicMock(name="discord")
        cog = _make_cog(tmp_path, config={"capabilities": ["me", "discord"]})
        procs = _mock_procs()
        rt = CogRuntime(cog, {"me": me_cap, "discord": discord_cap})
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["me"] is me_cap
        assert caps["discord"] is discord_cap

    def test_missing_string_capability_is_none(self, tmp_path):
        cog = _make_cog(tmp_path, config={"capabilities": ["nonexistent"]})
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["nonexistent"] is None

    def test_dict_capability_with_alias_and_scope(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path, config={
            "capabilities": [
                {"name": "dir", "alias": "mydata", "config": {"prefix": "custom/prefix/"}},
            ],
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {"dir": dir_cap})
        rt.run_cog(procs)

        dir_cap.scope.assert_any_call(prefix="custom/prefix/")
        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "mydata" in caps

    def test_dict_capability_no_config(self, tmp_path):
        me_cap = MagicMock(name="me")
        cog = _make_cog(tmp_path, config={
            "capabilities": [
                {"name": "me", "alias": "identity"},
            ],
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {"me": me_cap})
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["identity"] is me_cap

    def test_dict_capability_missing_is_none(self, tmp_path):
        cog = _make_cog(tmp_path, config={
            "capabilities": [
                {"name": "missing_cap", "alias": "alias"},
            ],
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["alias"] is None


# ---------------------------------------------------------------------------
# CogRuntime.run_coglet
# ---------------------------------------------------------------------------

class TestRunCoglet:
    def test_spawns_coglet(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={"handler": {"content": "I handle things."}})
        procs = _mock_procs()
        rt = CogRuntime(cog, {})

        handle = rt.run_coglet("handler", procs)

        procs.spawn.assert_called_once()
        kw = procs.spawn.call_args.kwargs
        assert kw["name"] == "mycog/handler"
        assert kw["content"] == "I handle things."
        assert handle is procs.spawn.return_value

    def test_coglet_gets_scoped_dir_and_data(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path, coglets={"worker": {}})
        procs = _mock_procs()
        rt = CogRuntime(cog, {"dir": dir_cap})
        rt.run_coglet("worker", procs)

        # Same scope as parent cog
        calls = dir_cap.scope.call_args_list
        prefixes = [c.kwargs.get("prefix") or c.args[0] for c in calls]
        assert "cogs/mycog/" in prefixes
        assert "data/mycog/" in prefixes

    def test_coglet_inherits_config_capabilities(self, tmp_path):
        me_cap = MagicMock(name="me")
        cog = _make_cog(tmp_path, coglets={
            "worker": {"config": {"capabilities": ["me"]}},
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {"me": me_cap})
        rt.run_coglet("worker", procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["me"] is me_cap

    def test_coglet_uses_own_config(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={
            "worker": {"config": {"mode": "daemon", "priority": 2.0}},
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_coglet("worker", procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["mode"] == "daemon"
        assert kw["priority"] == 2.0

    def test_coglet_not_found_raises(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = CogRuntime(cog, {})

        with pytest.raises(FileNotFoundError):
            rt.run_coglet("nonexistent", procs)

    def test_coglet_does_not_get_runtime(self, tmp_path):
        """Child coglets should NOT get the runtime capability (only main gets it)."""
        cog = _make_cog(tmp_path, coglets={"worker": {}})
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_coglet("worker", procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "runtime" not in caps

    def test_coglet_subscribe_from_handlers(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={
            "handler": {"config": {"handlers": ["discord.dm"]}},
        })
        procs = _mock_procs()
        rt = CogRuntime(cog, {})
        rt.run_coglet("handler", procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["subscribe"] == ["discord.dm"]
