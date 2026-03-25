"""Tests for cogtainer CI config loading."""

from __future__ import annotations

import yaml

from cogtainer.ci_config import CICogtainerEntry, CIConfig, load_ci_config


def test_load_ci_config(tmp_path):
    """Parse a valid cogtainers.ci.yml."""
    config_data = {
        "cogtainers": {
            "prod": {
                "account_id": "901289084804",
                "region": "us-east-1",
                "ecr_repo": "cogtainer-prod",
                "aws_role": "",
                "s3_artifacts_bucket": "",
                "components": "all",
                "cogents": [],
            },
            "staging": {
                "account_id": "123456789012",
                "region": "us-west-2",
                "ecr_repo": "cogtainer-staging",
                "components": ["lambdas", "dashboard"],
                "cogents": ["alpha", "beta"],
            },
        }
    }
    path = tmp_path / "cogtainers.ci.yml"
    path.write_text(yaml.dump(config_data))

    cfg = load_ci_config(path)

    assert len(cfg.cogtainers) == 2
    assert "prod" in cfg.cogtainers
    assert "staging" in cfg.cogtainers

    prod = cfg.cogtainers["prod"]
    assert prod.account_id == "901289084804"
    assert prod.region == "us-east-1"
    assert prod.ecr_repo == "cogtainer-prod"
    assert prod.components == "all"
    assert prod.cogents == []

    staging = cfg.cogtainers["staging"]
    assert staging.account_id == "123456789012"
    assert staging.region == "us-west-2"
    assert staging.components == ["lambdas", "dashboard"]
    assert staging.cogents == ["alpha", "beta"]


def test_load_ci_config_missing_file(tmp_path):
    """Return empty config when file doesn't exist."""
    cfg = load_ci_config(tmp_path / "nonexistent.yml")
    assert cfg.cogtainers == {}


def test_ci_config_deploy_targets():
    """deploy_targets returns sorted list of target dicts."""
    cfg = CIConfig(
        cogtainers={
            "staging": CICogtainerEntry(
                account_id="111111111111",
                region="us-west-2",
                ecr_repo="staging-repo",
                cogents=["test-cogent"],
            ),
            "prod": CICogtainerEntry(
                account_id="222222222222",
                ecr_repo="prod-repo",
            ),
        }
    )

    targets = cfg.deploy_targets()

    assert len(targets) == 2
    # Sorted by name, so prod comes first
    assert targets[0]["name"] == "prod"
    assert targets[0]["account_id"] == "222222222222"
    assert targets[0]["ecr_repo"] == "prod-repo"
    assert targets[0]["region"] == "us-east-1"  # default

    assert targets[1]["name"] == "staging"
    assert targets[1]["account_id"] == "111111111111"
    assert targets[1]["cogents"] == ["test-cogent"]


def test_ci_config_defaults():
    """Verify default field values."""
    entry = CICogtainerEntry(account_id="123", ecr_repo="repo")
    assert entry.region == "us-east-1"
    assert entry.components == "all"
    assert entry.cogents == []
    assert entry.aws_role == ""
