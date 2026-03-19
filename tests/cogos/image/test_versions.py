"""Tests for version manifest model and resolution."""
import json
import pytest
from cogos.image.versions import VersionManifest, resolve_versions


def test_manifest_roundtrip():
    m = VersionManifest(
        epoch=3,
        cogent_name="dr.alpha",
        components={
            "executor": "abc1234",
            "dashboard": "def5678",
            "dashboard_frontend": "ghi9012",
            "discord_bridge": "pqr2345",
            "lambda": "jkl3456",
            "cogos": "mno7890",
        },
    )
    data = json.loads(m.to_json())
    assert data["epoch"] == 3
    assert data["cogent_name"] == "dr.alpha"
    assert data["components"]["executor"] == "abc1234"
    assert "booted_at" in data

    m2 = VersionManifest.from_json(m.to_json())
    assert m2.epoch == m.epoch
    assert m2.components == m.components


def test_resolve_defaults_only():
    defaults = {"executor": "aaa", "dashboard": "bbb", "lambda": "ccc", "cogos": "ddd",
                "dashboard_frontend": "eee", "discord_bridge": "fff"}
    result = resolve_versions(defaults, overrides={})
    assert result == defaults


def test_resolve_with_overrides():
    defaults = {"executor": "aaa", "dashboard": "bbb", "lambda": "ccc", "cogos": "ddd",
                "dashboard_frontend": "eee", "discord_bridge": "fff"}
    result = resolve_versions(defaults, overrides={"executor": "zzz"})
    assert result["executor"] == "zzz"
    assert result["dashboard"] == "bbb"


def test_resolve_rejects_unknown_component():
    defaults = {"executor": "aaa"}
    with pytest.raises(ValueError, match="Unknown component"):
        resolve_versions(defaults, overrides={"bogus": "zzz"})
