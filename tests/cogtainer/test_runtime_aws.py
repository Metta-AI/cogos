"""Tests for AwsRuntime."""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from cogtainer.config import CogtainerEntry, LLMConfig
from cogtainer.runtime.aws import AwsRuntime


@pytest.fixture()
def aws_runtime() -> AwsRuntime:
    entry = CogtainerEntry(
        type="aws",
        region="us-east-1",
        llm=LLMConfig(provider="bedrock", model="test-model", api_key_env=""),
    )
    llm = MagicMock()
    session = MagicMock()
    return AwsRuntime(entry=entry, llm=llm, session=session)


# ── LLM delegation ──────────────────────────────────────────


def test_aws_runtime_converse_delegates(aws_runtime: AwsRuntime):
    expected = {"output": {"message": {"role": "assistant", "content": []}}}
    mock_llm = cast(MagicMock, aws_runtime._llm)
    mock_llm.converse.return_value = expected

    result = aws_runtime.converse(
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "sys"}],
        tool_config={},
    )

    assert result == expected
    mock_llm.converse.assert_called_once_with(
        messages=[{"role": "user", "content": [{"text": "hi"}]}],
        system=[{"text": "sys"}],
        tool_config={},
        model=None,
    )


# ── list_cogents ─────────────────────────────────────────────


def test_aws_runtime_list_cogents(aws_runtime: AwsRuntime):
    # Mock the DynamoDB table scan
    table = MagicMock()
    aws_runtime._session.resource.return_value.Table.return_value = table
    table.scan.return_value = {
        "Items": [
            {"cogent_name": "alpha"},
            {"cogent_name": "beta"},
        ],
    }

    result = aws_runtime.list_cogents()
    assert result == ["alpha", "beta"]
    aws_runtime._session.resource.assert_called_with("dynamodb", region_name="us-east-1")


# ── get_repository ───────────────────────────────────────────


def test_aws_runtime_get_repository(aws_runtime: AwsRuntime):
    table = MagicMock()
    aws_runtime._session.resource.return_value.Table.return_value = table
    table.get_item.return_value = {
        "Item": {
            "cogent_name": "alpha",
            "database": {
                "cluster_arn": "arn:aws:rds:us-east-1:123:cluster:my-cluster",
                "secret_arn": "arn:aws:secretsmanager:us-east-1:123:secret:my-secret",
                "db_name": "cogent_alpha",
            },
        },
    }

    repo = aws_runtime.get_repository("alpha")
    # Should have created an rds-data client and a Repository
    aws_runtime._session.client.assert_called_with("rds-data", region_name="us-east-1")


# ── put_file / get_file ─────────────────────────────────────


def test_aws_runtime_put_file(aws_runtime: AwsRuntime):
    s3 = MagicMock()
    aws_runtime._session.client.return_value = s3

    key = aws_runtime.put_file("alpha", "test.txt", b"hello")
    assert key == "test.txt"
    s3.put_object.assert_called_once()


def test_aws_runtime_get_file(aws_runtime: AwsRuntime):
    s3 = MagicMock()
    aws_runtime._session.client.return_value = s3
    s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"hello"))}

    result = aws_runtime.get_file("alpha", "test.txt")
    assert result == b"hello"


# ── emit_event ───────────────────────────────────────────────


def test_aws_runtime_emit_event(aws_runtime: AwsRuntime):
    eb = MagicMock()
    aws_runtime._session.client.return_value = eb

    aws_runtime.emit_event("alpha", {"type": "test"})
    eb.put_events.assert_called_once()


# ── spawn_executor ───────────────────────────────────────────


def test_aws_runtime_spawn_executor(aws_runtime: AwsRuntime):
    lam = MagicMock()
    aws_runtime._session.client.return_value = lam

    aws_runtime.spawn_executor("alpha", "proc-123")
    lam.invoke.assert_called_once()
    call_kwargs = lam.invoke.call_args[1]
    assert call_kwargs["InvocationType"] == "Event"
    assert "cogent-alpha-executor" in call_kwargs["FunctionName"]


# ── create/destroy ───────────────────────────────────────────


def test_aws_runtime_create_cogent(aws_runtime: AwsRuntime):
    """create_cogent creates DB, registers in status table, applies schema."""
    aws_runtime._cogtainer_name = "test"
    aws_runtime._status_table = "cogtainer-test-status"

    rds_client = MagicMock()
    cf_client = MagicMock()
    cf_client.describe_stacks.return_value = {
        "Stacks": [{"Outputs": [
            {"OutputKey": "DbClusterArn", "OutputValue": "arn:rds:cluster"},
            {"OutputKey": "DbSecretArn", "OutputValue": "arn:secret"},
        ]}]
    }

    def mock_client(service, **kw):
        return cf_client if service == "cloudformation" else rds_client
    aws_runtime._session.client.side_effect = mock_client

    mock_table = MagicMock()
    aws_runtime._session.resource.return_value.Table.return_value = mock_table

    with patch("cogos.db.migrations.apply_schema_with_client"):
        aws_runtime.create_cogent("alpha")

    mock_table.put_item.assert_called_once()
    rds_client.execute_statement.assert_called_once()  # CREATE DATABASE


def test_aws_runtime_destroy_cogent(aws_runtime: AwsRuntime):
    """destroy_cogent removes from status table."""
    mock_table = MagicMock()
    aws_runtime._session.resource.return_value.Table.return_value = mock_table
    aws_runtime.destroy_cogent("alpha")
    mock_table.delete_item.assert_called_once_with(Key={"cogent_name": "alpha"})
