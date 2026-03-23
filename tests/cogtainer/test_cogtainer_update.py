"""Tests for cogtainer update command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from cogtainer.cogtainer_cli import cli


def _make_ddb_table_mock(cogent_names: list[str]):
    """Create a mock DynamoDB table that returns given cogent names."""
    items = [{"cogent_name": name} for name in cogent_names]
    table = MagicMock()
    table.scan.return_value = {"Items": items}
    return table


def _mock_aws_session(cogent_names: list[str], service_arns: list[str] | None = None):
    """Return (session_mock, lambda_mock, ecs_mock)."""
    session = MagicMock()
    table = _make_ddb_table_mock(cogent_names)
    ddb_resource = MagicMock()
    ddb_resource.Table.return_value = table
    session.resource.return_value = ddb_resource

    lambda_client = MagicMock()
    lambda_client.exceptions = MagicMock()
    lambda_client.exceptions.ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

    ecs_client = MagicMock()
    ecs_client.exceptions = MagicMock()
    ecs_client.exceptions.ServiceNotFoundException = type("ServiceNotFoundException", (Exception,), {})
    ecs_client.describe_clusters.return_value = {"clusters": []}

    paginator = MagicMock()
    paginator.paginate.return_value = [{"serviceArns": service_arns or []}]
    ecs_client.get_paginator.return_value = paginator

    def client_factory(service, **kwargs):
        if service == "lambda":
            return lambda_client
        if service == "ecs":
            return ecs_client
        return MagicMock()

    session.client.side_effect = client_factory

    return session, lambda_client, ecs_client


@patch("cogtainer.cogtainer_cli._get_aws_session")
def test_update_lambdas_only(mock_get_session, tmp_path, monkeypatch):
    """--lambdas flag should call update_function_code for each cogent's Lambda functions."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text(yaml.dump({
        "cogtainers": {"prod": {"type": "aws", "region": "us-east-1"}},
        "defaults": {"cogtainer": "prod"},
    }))
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    session, lambda_client, ecs_client = _mock_aws_session(["alpha", "beta.test"])
    mock_get_session.return_value = (session, "901289084804")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "update", "prod",
        "--lambdas",
        "--lambda-s3-bucket", "my-bucket",
        "--lambda-s3-key", "lambda.zip",
    ])

    assert result.exit_code == 0, result.output
    assert "Updating Lambda functions" in result.output

    # Should have called update_function_code for each cogent x suffix
    calls = lambda_client.update_function_code.call_args_list
    called_functions = {call.kwargs["FunctionName"] for call in calls}

    assert "cogtainer-prod-alpha-event-router" in called_functions
    assert "cogtainer-prod-alpha-executor" in called_functions
    assert "cogtainer-prod-alpha-dispatcher" in called_functions
    assert "cogtainer-prod-beta-test-event-router" in called_functions

    # Verify S3 params
    for call in calls:
        assert call.kwargs["S3Bucket"] == "my-bucket"
        assert call.kwargs["S3Key"] == "lambda.zip"

    # ECS should NOT have been called
    ecs_client.update_service.assert_not_called()


@patch("cogtainer.cogtainer_cli._get_aws_session")
def test_update_services_only(mock_get_session, tmp_path, monkeypatch):
    """--services flag should call update_service for each cogent's ECS services."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text(yaml.dump({
        "cogtainers": {"prod": {"type": "aws", "region": "us-east-1"}},
        "defaults": {"cogtainer": "prod"},
    }))
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    session, lambda_client, ecs_client = _mock_aws_session(
        ["alpha"],
        service_arns=[
            "arn:aws:ecs:us-east-1:901289084804:service/cogtainer/cogent-alpha-dashboard",
            "arn:aws:ecs:us-east-1:901289084804:service/cogtainer/cogent-alpha-discord",
        ],
    )
    mock_get_session.return_value = (session, "901289084804")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "update", "prod",
        "--services",
    ])

    assert result.exit_code == 0, result.output
    assert "Restarting ECS services" in result.output

    # Should have called update_service for dashboard + discord
    calls = ecs_client.update_service.call_args_list
    called_services = {call.kwargs["service"] for call in calls}

    assert "cogent-alpha-dashboard" in called_services
    assert "cogent-alpha-discord" in called_services

    # All calls should have forceNewDeployment=True
    for call in calls:
        assert call.kwargs["forceNewDeployment"] is True

    # Lambda should NOT have been called
    lambda_client.update_function_code.assert_not_called()


@patch("cogtainer.cogtainer_cli._get_aws_session")
def test_update_default_updates_both(mock_get_session, tmp_path, monkeypatch):
    """No flags should update both lambdas and services (requires s3 args for lambdas)."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text(yaml.dump({
        "cogtainers": {"prod": {"type": "aws"}},
        "defaults": {"cogtainer": "prod"},
    }))
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    session, lambda_client, ecs_client = _mock_aws_session(
        ["gamma"],
        service_arns=["arn:aws:ecs:us-east-1:901289084804:service/cogtainer/cogent-gamma-dashboard"],
    )
    mock_get_session.return_value = (session, "901289084804")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "update", "prod",
        "--lambda-s3-bucket", "b",
        "--lambda-s3-key", "k",
    ])

    assert result.exit_code == 0, result.output
    assert "Updating Lambda functions" in result.output
    assert "Restarting ECS services" in result.output

    # Both should have been called
    assert lambda_client.update_function_code.called
    assert ecs_client.update_service.called


@patch("cogtainer.cogtainer_cli._get_aws_session")
def test_update_no_cogents(mock_get_session, tmp_path, monkeypatch):
    """When no cogents found, exit gracefully."""
    config_path = tmp_path / "cogtainers.yml"
    config_path.write_text(yaml.dump({
        "cogtainers": {"prod": {"type": "aws"}},
        "defaults": {"cogtainer": "prod"},
    }))
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))

    session, _, _ = _mock_aws_session([])
    mock_get_session.return_value = (session, "901289084804")

    runner = CliRunner()
    result = runner.invoke(cli, ["update", "prod", "--lambdas"])

    assert result.exit_code == 0
    assert "No cogents found" in result.output
