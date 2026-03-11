from __future__ import annotations

import pytest

from brain.update_cli import _find_dashboard_service, _is_dashboard_service_name


class _FakeEcsClient:
    def __init__(self, service_arns: list[str]):
        self.service_arns = service_arns

    def list_services(self, cluster: str) -> dict[str, list[str]]:
        assert cluster == "cogent-polis"
        return {"serviceArns": self.service_arns}


def test_is_dashboard_service_name_rejects_non_dashboard_services():
    assert _is_dashboard_service_name("cogent-dr-gamma-brain-DashService09A25EB6-mc4IBPRXHnGZ", "dr-gamma")
    assert _is_dashboard_service_name("cogent-dr-gamma-dashboard", "dr-gamma")
    assert not _is_dashboard_service_name("cogent-dr-gamma-discord", "dr-gamma")


def test_find_dashboard_service_prefers_dashboard_service_over_discord():
    ecs_client = _FakeEcsClient(
        [
            "arn:aws:ecs:us-east-1:901289084804:service/cogent-polis/cogent-dr-gamma-discord",
            "arn:aws:ecs:us-east-1:901289084804:service/cogent-polis/cogent-dr-gamma-brain-DashService09A25EB6-mc4IBPRXHnGZ",
        ]
    )

    service_arn = _find_dashboard_service(ecs_client, "dr-gamma")

    assert service_arn.endswith("cogent-dr-gamma-brain-DashService09A25EB6-mc4IBPRXHnGZ")


def test_find_dashboard_service_raises_when_dashboard_service_missing():
    ecs_client = _FakeEcsClient(
        ["arn:aws:ecs:us-east-1:901289084804:service/cogent-polis/cogent-dr-gamma-discord"]
    )

    with pytest.raises(Exception, match="No dashboard service found"):
        _find_dashboard_service(ecs_client, "dr-gamma")
