"""Tests for AwsRuntime."""

from __future__ import annotations

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
    return AwsRuntime(entry=entry, llm=llm, session=session, cogtainer_name="test-ct")


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


def test_aws_runtime_get_repository(aws_runtime: AwsRuntime, monkeypatch):
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:aws:rds:us-east-1:123:cluster:my-cluster")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:my-secret")
    monkeypatch.setenv("DB_NAME", "cogent_alpha")

    _repo = aws_runtime.get_repository("alpha")
    # Should have created an rds-data client and a Repository
    aws_runtime._session.client.assert_called_with("rds-data", region_name="us-east-1")


def test_aws_runtime_get_repository_uses_db_info_fallback(aws_runtime: AwsRuntime, monkeypatch):
    """get_repository should use _get_db_info() when env vars are not set."""
    monkeypatch.delenv("DB_CLUSTER_ARN", raising=False)
    monkeypatch.delenv("DB_SECRET_ARN", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    # Mock _get_db_info to return stack-derived values
    aws_runtime._db_info_cache = {
        "cluster_arn": "arn:rds:from-stack",
        "secret_arn": "arn:secret:from-stack",
    }

    repo = aws_runtime.get_repository("my.cogent")
    # DB name should be derived from cogent name
    assert repo._database == "cogent_my_cogent"
    assert repo._resource_arn == "arn:rds:from-stack"
    assert repo._secret_arn == "arn:secret:from-stack"


def test_aws_runtime_get_repository_env_overrides_db_info(aws_runtime: AwsRuntime, monkeypatch):
    """Env vars should take precedence when _get_db_info returns empty strings."""
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:rds:from-env")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:secret:from-env")
    monkeypatch.setenv("DB_NAME", "custom_db")

    # _get_db_info returns empty (no stack outputs)
    aws_runtime._db_info_cache = {"cluster_arn": "", "secret_arn": ""}

    repo = aws_runtime.get_repository("alpha")
    assert repo._resource_arn == "arn:rds:from-env"
    assert repo._secret_arn == "arn:secret:from-env"
    assert repo._database == "custom_db"


def test_aws_runtime_get_repository_db_name_derived_from_cogent(aws_runtime: AwsRuntime, monkeypatch):
    """Without DB_NAME env var, db name should be cogent_{safe_name}."""
    monkeypatch.delenv("DB_NAME", raising=False)
    aws_runtime._db_info_cache = {
        "cluster_arn": "arn:rds:cluster",
        "secret_arn": "arn:secret:secret",
    }

    repo = aws_runtime.get_repository("dr.alpha")
    # _safe replaces . with -, then replace - with _ for db name
    assert repo._database == "cogent_dr_alpha"


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
    assert call_kwargs["FunctionName"] == "cogtainer-test-ct-alpha-executor"


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

    with patch("cogos.db.migrations.apply_schema_with_client"), \
         patch.object(aws_runtime, "_deploy_cogent_stack"):
        aws_runtime.create_cogent("alpha")

    mock_table.put_item.assert_called_once()
    rds_client.execute_statement.assert_called_once()  # CREATE DATABASE


def test_aws_runtime_destroy_cogent(aws_runtime: AwsRuntime):
    """destroy_cogent removes from status table."""
    mock_table = MagicMock()
    aws_runtime._session.resource.return_value.Table.return_value = mock_table
    aws_runtime.destroy_cogent("alpha")
    mock_table.delete_item.assert_called_once_with(Key={"cogent_name": "alpha"})
