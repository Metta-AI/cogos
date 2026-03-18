"""Tests for CogletRuntime — spawning cogs and coglets from directory structure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cogos.cog.cog import Cog, CogConfig
from cogos.cog.runtime import CogManifest, CogletManifest, CogletRuntime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cog(tmp_path, *, name="mycog", config=None, coglets=None):
    """Create a cog directory and return a Cog."""
    cog_dir = tmp_path / name
    cog_dir.mkdir(parents=True, exist_ok=True)
    (cog_dir / "main.md").write_text("You are the main coglet.")

    if config is not None:
        (cog_dir / "cog.py").write_text(
            "from cogos.cog.cog import CogConfig\n"
            f"config = CogConfig(**{config!r})\n"
        )

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


def _make_runtime(cog, cap_objects=None):
    """Create a CogletRuntime from a filesystem Cog."""
    return CogletRuntime.from_cog(cog, cap_objects or {})


def _mock_cap(name="cap"):
    cap = MagicMock(name=name)
    scoped = MagicMock(name=f"{name}_scoped")
    cap.scope.return_value = scoped
    return cap


def _mock_procs():
    procs = MagicMock(name="procs")
    handle = MagicMock(name="process_handle")
    procs.spawn.return_value = handle
    return procs


# ---------------------------------------------------------------------------
# CogManifest
# ---------------------------------------------------------------------------

class TestCogManifest:
    def test_from_cog(self, tmp_path):
        cog = _make_cog(tmp_path, config={"mode": "daemon"}, coglets={
            "handler": {"content": "I handle.", "config": {"mode": "daemon"}},
        })
        m = CogManifest.from_cog(cog)
        assert m.name == "mycog"
        assert m.config.mode == "daemon"
        assert m.content == "You are the main coglet."
        assert "handler" in m.coglets
        assert m.coglets["handler"].content == "I handle."

    def test_round_trip_to_dict_from_dict(self, tmp_path):
        cog = _make_cog(tmp_path, config={"mode": "daemon", "priority": 5.0}, coglets={
            "worker": {"content": "I work.", "config": {"mode": "one_shot"}},
        })
        m = CogManifest.from_cog(cog)
        data = m.to_dict()

        # Simulate FileStore reads
        files = {
            f"apps/mycog/main.md": "You are the main coglet.",
            f"apps/mycog/worker/main.md": "I work.",
        }
        m2 = CogManifest.from_dict(data, lambda k: files[k])
        assert m2.name == "mycog"
        assert m2.config.mode == "daemon"
        assert m2.config.priority == 5.0
        assert m2.content == "You are the main coglet."
        assert m2.coglets["worker"].content == "I work."
        assert m2.coglets["worker"].config.mode == "one_shot"


# ---------------------------------------------------------------------------
# CogletRuntime.run_cog
# ---------------------------------------------------------------------------

class TestRunCog:
    def test_spawns_main_coglet(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = _make_runtime(cog)
        handle = rt.run_cog(procs)

        procs.spawn.assert_called_once()
        kw = procs.spawn.call_args.kwargs
        assert kw["name"] == "mycog"
        assert kw["detached"] is True
        assert handle is procs.spawn.return_value

    def test_passes_content_from_entrypoint(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_cog(procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["content"] == "You are the main coglet."

    def test_passes_mode_from_config(self, tmp_path):
        cog = _make_cog(tmp_path, config={"mode": "daemon"})
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_cog(procs)

        assert procs.spawn.call_args.kwargs["mode"] == "daemon"

    def test_passes_config_fields(self, tmp_path):
        cog = _make_cog(tmp_path, config={
            "mode": "daemon", "priority": 5.0, "executor": "llm",
            "model": "gpt-4", "runner": "ecs", "idle_timeout_ms": 3000,
        })
        procs = _mock_procs()
        rt = _make_runtime(cog)
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
        rt = _make_runtime(cog)
        rt.run_cog(procs)

        assert procs.spawn.call_args.kwargs["subscribe"] == ["discord.*", "email.*"]

    def test_adds_scoped_dir(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = _make_runtime(cog, {"dir": dir_cap})
        rt.run_cog(procs)

        dir_cap.scope.assert_any_call(prefix="cogs/mycog/")
        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "dir" in caps

    def test_adds_scoped_data(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = _make_runtime(cog, {"dir": dir_cap})
        rt.run_cog(procs)

        calls = dir_cap.scope.call_args_list
        prefixes = [c.kwargs.get("prefix") or c.args[0] for c in calls]
        assert "data/mycog/" in prefixes

    def test_adds_runtime_self(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["runtime"] is rt

    def test_string_capabilities_looked_up(self, tmp_path):
        me_cap = MagicMock(name="me")
        discord_cap = MagicMock(name="discord")
        cog = _make_cog(tmp_path, config={"capabilities": ["me", "discord"]})
        procs = _mock_procs()
        rt = _make_runtime(cog, {"me": me_cap, "discord": discord_cap})
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["me"] is me_cap
        assert caps["discord"] is discord_cap

    def test_missing_string_capability_is_none(self, tmp_path):
        cog = _make_cog(tmp_path, config={"capabilities": ["nonexistent"]})
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_cog(procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert caps["nonexistent"] is None

    def test_dict_capability_with_alias_and_scope(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path, config={
            "capabilities": [{"name": "dir", "alias": "mydata", "config": {"prefix": "custom/"}}],
        })
        procs = _mock_procs()
        rt = _make_runtime(cog, {"dir": dir_cap})
        rt.run_cog(procs)

        dir_cap.scope.assert_any_call(prefix="custom/")
        assert "mydata" in procs.spawn.call_args.kwargs["capabilities"]


# ---------------------------------------------------------------------------
# CogletRuntime.run_coglet
# ---------------------------------------------------------------------------

class TestRunCoglet:
    def test_spawns_coglet(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={"handler": {"content": "I handle things."}})
        procs = _mock_procs()
        rt = _make_runtime(cog)
        handle = rt.run_coglet("handler", procs)

        procs.spawn.assert_called_once()
        kw = procs.spawn.call_args.kwargs
        assert kw["name"] == "mycog/handler"
        assert kw["content"] == "I handle things."

    def test_coglet_gets_scoped_dir_and_data(self, tmp_path):
        dir_cap = _mock_cap("dir")
        cog = _make_cog(tmp_path, coglets={"worker": {}})
        procs = _mock_procs()
        rt = _make_runtime(cog, {"dir": dir_cap})
        rt.run_coglet("worker", procs)

        calls = dir_cap.scope.call_args_list
        prefixes = [c.kwargs.get("prefix") or c.args[0] for c in calls]
        assert "cogs/mycog/" in prefixes
        assert "data/mycog/" in prefixes

    def test_coglet_uses_own_config(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={
            "worker": {"config": {"mode": "daemon", "priority": 2.0}},
        })
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_coglet("worker", procs)

        kw = procs.spawn.call_args.kwargs
        assert kw["mode"] == "daemon"
        assert kw["priority"] == 2.0

    def test_coglet_not_found_raises(self, tmp_path):
        cog = _make_cog(tmp_path)
        procs = _mock_procs()
        rt = _make_runtime(cog)

        with pytest.raises(FileNotFoundError):
            rt.run_coglet("nonexistent", procs)

    def test_coglet_does_not_get_runtime(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={"worker": {}})
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_coglet("worker", procs)

        caps = procs.spawn.call_args.kwargs["capabilities"]
        assert "runtime" not in caps

    def test_coglet_subscribe_from_handlers(self, tmp_path):
        cog = _make_cog(tmp_path, coglets={
            "handler": {"config": {"handlers": ["discord.dm"]}},
        })
        procs = _mock_procs()
        rt = _make_runtime(cog)
        rt.run_coglet("handler", procs)

        assert procs.spawn.call_args.kwargs["subscribe"] == ["discord.dm"]
