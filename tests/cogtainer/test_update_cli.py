from __future__ import annotations

import pytest
from click.testing import CliRunner

from cogtainer.update_cli import (
    _find_dashboard_service,
    _is_dashboard_service_name,
    update,
)
from cogtainer.aws import ACCOUNT_ID
from cogtainer import naming


class _FakeEcsClient:
    def __init__(self, service_arns: list[str]):
        self.service_arns = service_arns

    def list_services(self, cluster: str) -> dict[str, list[str]]:
        assert cluster == naming.cluster_name()
        return {"serviceArns": self.service_arns}


def test_is_dashboard_service_name_rejects_non_dashboard_services():
    assert _is_dashboard_service_name("cogent-dr-gamma-cogtainer-DashService09A25EB6-mc4IBPRXHnGZ", "dr-gamma")
    assert _is_dashboard_service_name("cogent-dr-gamma-dashboard", "dr-gamma")
    assert not _is_dashboard_service_name("cogent-dr-gamma-discord", "dr-gamma")


def test_find_dashboard_service_prefers_dashboard_service_over_discord():
    cluster = naming.cluster_name()
    ecs_client = _FakeEcsClient(
        [
            f"arn:aws:ecs:us-east-1:{ACCOUNT_ID}:service/{cluster}/cogent-dr-gamma-discord",
            f"arn:aws:ecs:us-east-1:{ACCOUNT_ID}:service/{cluster}/cogent-dr-gamma-cogtainer-DashService09A25EB6-mc4IBPRXHnGZ",
        ]
    )

    service_arn = _find_dashboard_service(ecs_client, "dr-gamma")

    assert service_arn.endswith("cogent-dr-gamma-cogtainer-DashService09A25EB6-mc4IBPRXHnGZ")


def test_find_dashboard_service_raises_when_dashboard_service_missing():
    cluster = naming.cluster_name()
    ecs_client = _FakeEcsClient(
        [f"arn:aws:ecs:us-east-1:{ACCOUNT_ID}:service/{cluster}/cogent-dr-gamma-discord"]
    )

    with pytest.raises(Exception, match="No dashboard service found"):
        _find_dashboard_service(ecs_client, "dr-gamma")



def test_update_rds_runs_brain_and_cogos_migrations(monkeypatch):
    calls: dict[str, object] = {}
    fake_repo = object()

    monkeypatch.setattr(
        "cogtainer.update_cli._ensure_db_env", lambda name, profile=None: calls.setdefault("ensure", (name, profile))
    )
    monkeypatch.setattr("cogos.db.migrations.apply_schema", lambda: 10)
    monkeypatch.setattr(
        "cogos.db.migrations.apply_cogos_sql_migrations",
        lambda repo: calls.__setitem__("repo", repo) or 42,
    )
    monkeypatch.setenv("DB_CLUSTER_ARN", "cluster-arn")
    monkeypatch.setenv("DB_SECRET_ARN", "secret-arn")
    monkeypatch.setenv("DB_NAME", "cogent")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(
        "cogos.db.repository.Repository.create",
        lambda **kwargs: calls.__setitem__("repo_create", kwargs) or fake_repo,
    )

    runner = CliRunner()
    result = runner.invoke(update, ["rds"], obj={"cogent_id": "dr.gamma"})

    assert result.exit_code == 0
    assert calls["ensure"] == ("dr.gamma", None)
    assert calls["repo"] is fake_repo
    assert calls["repo_create"] == {
        "resource_arn": "cluster-arn",
        "secret_arn": "secret-arn",
        "database": "cogent",
        "region": "us-east-1",
    }
    assert "Schema at version 10." in result.output
    assert "CogOS SQL migrations applied" in result.output
