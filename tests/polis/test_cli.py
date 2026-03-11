from __future__ import annotations

import io
from types import SimpleNamespace

from click.testing import CliRunner
from rich.console import Console

import polis.cli as cli_mod
from polis.cli import polis


def test_update_ensures_polis_quotas(monkeypatch):
    calls: list[tuple] = []

    monkeypatch.setattr("polis.cli.get_org_id", lambda: "o-test")
    monkeypatch.setattr("polis.cli._cdk_deploy", lambda org_id, profile=None: calls.append(("deploy", org_id, profile)))
    monkeypatch.setattr("polis.cli.get_polis_session", lambda: ("session", "901289084804"))
    monkeypatch.setattr(
        "polis.cli._ensure_polis_quotas",
        lambda session, config, **kwargs: calls.append(("quotas", session, config.domain)),
    )
    monkeypatch.setattr(
        "polis.cli._ensure_cloudflare_access",
        lambda session, domain: calls.append(("cloudflare", session, domain)),
    )

    runner = CliRunner()
    result = runner.invoke(polis, ["update"])

    assert result.exit_code == 0
    assert calls == [
        ("deploy", "o-test", "softmax-org"),
        ("quotas", "session", "softmax-cogents.com"),
        ("cloudflare", "session", "softmax-cogents.com"),
    ]


def test_quotas_ensure_runs_quota_helper(monkeypatch):
    calls: list[tuple] = []

    monkeypatch.setattr("polis.cli.get_polis_session", lambda: ("session", "901289084804"))
    monkeypatch.setattr(
        "polis.cli._ensure_polis_quotas",
        lambda session, config, **kwargs: calls.append(("quotas", session, config.domain, kwargs.get("fail_on_error"))),
    )

    runner = CliRunner()
    result = runner.invoke(polis, ["quotas", "ensure"])

    assert result.exit_code == 0
    assert calls == [("quotas", "session", "softmax-cogents.com", True)]

class FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        return list(self._pages)


class FakeEcrClient:
    def describe_repositories(self, repositoryNames):
        return {"repositories": [{"repositoryUri": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent"}]}

    def describe_images(self, repositoryName, filter):
        return {"imageDetails": []}


class FakeEcsClient:
    def __init__(self):
        self.list_services_called = False

    def describe_clusters(self, clusters):
        return {"clusters": [{"runningTasksCount": 2}]}

    def list_services(self, cluster):
        self.list_services_called = True
        return {"serviceArns": []}


class FakeSecretsManagerClient:
    def get_paginator(self, name):
        assert name == "list_secrets"
        return FakePaginator(
            [
                {
                    "SecretList": [
                        {"Name": "cogent/dr.gamma/github"},
                    ]
                }
            ]
        )


class FakeEventsClient:
    def list_event_buses(self, NamePrefix):
        return {"EventBuses": [{"Name": "cogent-dr-gamma"}]}

    def list_rules(self, EventBusName):
        return {"Rules": [{"State": "ENABLED"}, {"State": "DISABLED"}]}


class FakeStatusTable:
    def scan(self, **kwargs):
        return {
            "Items": [
                {
                    "cogent_name": "dr.gamma",
                    "stack_status": "UPDATE_COMPLETE",
                    "domain": "dr-gamma.softmax-cogents.com",
                    "channels": {"github": "ok"},
                    "dashboard_url": "https://dr-gamma.softmax-cogents.com",
                    "dashboard": {
                        "status": "ACTIVE",
                        "running_count": 1,
                        "desired_count": 1,
                        "image": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent:dr-gamma-dashboard",
                        "cpu_1m": 9,
                        "cpu_10m": 7,
                        "mem_pct": 41,
                    },
                    "executor": {
                        "image": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent:executor-dr-gamma",
                    },
                }
            ]
        }


class FakeDynamoResource:
    def Table(self, name):
        assert name == "cogent-status"
        return FakeStatusTable()


class FakeSession:
    def __init__(self):
        self.ecs = FakeEcsClient()

    def client(self, name):
        if name == "ecr":
            return FakeEcrClient()
        if name == "ecs":
            return self.ecs
        if name == "secretsmanager":
            return FakeSecretsManagerClient()
        if name == "events":
            return FakeEventsClient()
        raise AssertionError(f"Unexpected client: {name}")

    def resource(self, name):
        assert name == "dynamodb"
        return FakeDynamoResource()


def test_status_renders_stored_snapshot_without_listing_dashboard_services(monkeypatch):
    output = io.StringIO()
    fake_session = FakeSession()

    monkeypatch.setattr(
        cli_mod,
        "console",
        Console(file=output, force_terminal=False, color_system=None, width=160),
    )
    monkeypatch.setattr(cli_mod, "get_polis_session", lambda: (fake_session, None))
    monkeypatch.setattr(cli_mod, "PolisConfig", lambda: SimpleNamespace(domain="softmax-cogents.com"))

    assert cli_mod.status.callback is not None
    cli_mod.status.callback()

    rendered = output.getvalue()
    assert "dr-gamma-dashboard" in rendered
    assert "executor-dr-gamma" in rendered
    assert "1/2 rules enabled" in rendered
    assert not fake_session.ecs.list_services_called
