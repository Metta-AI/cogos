"""Tests for version manifest model and resolution."""
import json
from unittest.mock import MagicMock

import pytest

from cogos.image.versions import (
    ArtifactMissing,
    VersionManifest,
    load_defaults,
    resolve_versions,
    verify_artifacts,
    write_versions_to_filestore,
)


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


def test_verify_all_present(tmp_path):
    components = {"executor": "abc", "dashboard": "def", "dashboard_frontend": "ghi",
                  "discord_bridge": "pqr", "lambda": "jkl", "cogos": "mno"}
    ecr = MagicMock()
    ecr.describe_images = MagicMock(return_value={})
    s3 = MagicMock()
    s3.head_object = MagicMock(return_value={})
    verify_artifacts(components, ecr_client=ecr, s3_client=s3, artifacts_bucket="test-bucket", ecr_repo="test-repo")


def test_verify_ecr_missing():
    components = {"executor": "abc", "dashboard": "def", "dashboard_frontend": "ghi",
                  "discord_bridge": "pqr", "lambda": "jkl", "cogos": "mno"}
    ecr = MagicMock()
    ecr.describe_images = MagicMock(side_effect=Exception("not found"))
    s3 = MagicMock()
    s3.head_object = MagicMock(return_value={})
    with pytest.raises(ArtifactMissing, match="executor"):
        verify_artifacts(components, ecr_client=ecr, s3_client=s3, artifacts_bucket="test-bucket", ecr_repo="test-repo")


def test_verify_s3_missing():
    components = {"executor": "abc", "dashboard": "def", "dashboard_frontend": "ghi",
                  "discord_bridge": "pqr", "lambda": "jkl", "cogos": "mno"}
    ecr = MagicMock()
    ecr.describe_images = MagicMock(return_value={})
    s3 = MagicMock()

    def _head(Bucket, Key):
        if "lambda" in Key:
            raise Exception("not found")
        return {}

    s3.head_object = MagicMock(side_effect=_head)
    with pytest.raises(ArtifactMissing, match="lambda"):
        verify_artifacts(components, ecr_client=ecr, s3_client=s3, artifacts_bucket="test-bucket", ecr_repo="test-repo")


def test_verify_skipped_for_local():
    components = {"executor": "local", "dashboard": "local", "dashboard_frontend": "local",
                  "discord_bridge": "local", "lambda": "local", "cogos": "local"}
    verify_artifacts(components, ecr_client=None, s3_client=None, artifacts_bucket="test-bucket", ecr_repo="test-repo")


def test_load_defaults(tmp_path):
    defaults_file = tmp_path / "versions.defaults.json"
    defaults_file.write_text(json.dumps({
        "executor": "aaa", "dashboard": "bbb", "dashboard_frontend": "ccc",
        "discord_bridge": "ddd", "lambda": "eee", "cogos": "fff",
    }))
    result = load_defaults(tmp_path)
    assert result["executor"] == "aaa"
    assert len(result) == 6

def test_load_defaults_missing(tmp_path):
    result = load_defaults(tmp_path)
    for v in result.values():
        assert v == "local"


def test_write_versions_to_filestore():
    manifest = VersionManifest(
        epoch=1, cogent_name="test",
        components={"executor": "aaa", "dashboard": "bbb", "dashboard_frontend": "ccc",
                     "discord_bridge": "ddd", "lambda": "eee", "cogos": "fff"},
    )
    fs = MagicMock()
    write_versions_to_filestore(manifest, fs)
    fs.upsert.assert_called_once()
    call_args = fs.upsert.call_args
    assert call_args[0][0] == "mnt/boot/versions.json"
    written = json.loads(call_args[0][1])
    assert written["epoch"] == 1
    assert written["components"]["executor"] == "aaa"
