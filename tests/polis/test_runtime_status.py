import pytest

from polis.runtime_status import load_status_manifest, resolve_runtime_status


class FakeEcsClient:
    def __init__(self):
        self._services = {}
        self._task_definitions = {}

    def add_service(self, cluster: str, service_arn: str, service: dict):
        self._services[(cluster, service_arn)] = service

    def add_task_definition(self, task_definition_arn: str, container_definitions: list[dict]):
        self._task_definitions[task_definition_arn] = {
            "containerDefinitions": container_definitions,
        }

    def describe_services(self, cluster: str, services: list[str]) -> dict:
        return {
            "services": [
                self._services[(cluster, service_arn)]
                for service_arn in services
                if (cluster, service_arn) in self._services
            ]
        }

    def describe_task_definition(self, taskDefinition: str) -> dict:
        return {"taskDefinition": self._task_definitions[taskDefinition]}


class FakeCloudWatchClient:
    def __init__(self, results: list[dict]):
        self.results = results
        self.calls = []

    def get_metric_data(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"MetricDataResults": self.results}


def test_load_status_manifest_prefers_output_and_backfills_dashboard_url():
    stack = {
        "Outputs": [
            {
                "OutputKey": "StatusManifest",
                "OutputValue": (
                    '{"version": 1, "cogent_name": "dr.gamma", '
                    '"dashboard": {"service_arn": "arn:aws:ecs:us-east-1:123:service/'
                    'cogent-polis/cogent-dr-gamma-dashboard", "container_name": "web"}}'
                ),
            },
            {
                "OutputKey": "DashboardUrl",
                "OutputValue": "https://dr-gamma.softmax-cogents.com",
            },
        ],
        "Tags": [{"Key": "cogent_name", "Value": "ignored-by-manifest"}],
    }

    manifest = load_status_manifest(stack)

    assert manifest["version"] == 1
    assert manifest["cogent_name"] == "dr.gamma"
    assert manifest["dashboard"]["container_name"] == "web"
    assert manifest["dashboard"]["url"] == "https://dr-gamma.softmax-cogents.com"


def test_load_status_manifest_requires_explicit_identity():
    with pytest.raises(ValueError, match="missing StatusManifest.cogent_name"):
        load_status_manifest({"Outputs": [], "Tags": []})


def test_resolve_runtime_status_uses_live_component_images():
    dashboard_service_arn = (
        "arn:aws:ecs:us-east-1:123456789012:service/"
        "cogent-polis/cogent-dr-gamma-dashboard"
    )
    discord_service_arn = (
        "arn:aws:ecs:us-east-1:123456789012:service/"
        "cogent-polis/cogent-dr-gamma-discord"
    )
    dashboard_task_definition = "arn:aws:ecs:us-east-1:123456789012:task-definition/dashboard:7"
    discord_task_definition = "arn:aws:ecs:us-east-1:123456789012:task-definition/discord:5"
    executor_task_definition = "arn:aws:ecs:us-east-1:123456789012:task-definition/executor:9"

    ecs_client = FakeEcsClient()
    ecs_client.add_service(
        "cogent-polis",
        dashboard_service_arn,
        {
            "serviceName": "cogent-dr-gamma-dashboard",
            "status": "ACTIVE",
            "runningCount": 1,
            "desiredCount": 1,
            "taskDefinition": dashboard_task_definition,
        },
    )
    ecs_client.add_service(
        "cogent-polis",
        discord_service_arn,
        {
            "serviceName": "cogent-dr-gamma-discord",
            "status": "ACTIVE",
            "runningCount": 0,
            "desiredCount": 0,
            "taskDefinition": discord_task_definition,
        },
    )
    ecs_client.add_task_definition(
        dashboard_task_definition,
        [
            {
                "name": "web",
                "image": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent:dr-gamma-dashboard",
            }
        ],
    )
    ecs_client.add_task_definition(
        discord_task_definition,
        [{"name": "bridge", "image": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent:discord-bridge"}],
    )
    ecs_client.add_task_definition(
        executor_task_definition,
        [
            {
                "name": "Executor",
                "image": "901289084804.dkr.ecr.us-east-1.amazonaws.com/cogent:executor-dr-gamma",
            }
        ],
    )

    cloudwatch_client = FakeCloudWatchClient(
        [
            {"Id": "c0", "Values": [17.0, 13.0]},
            {"Id": "m0", "Values": [42.0]},
            {"Id": "c1", "Values": [0.0]},
            {"Id": "m1", "Values": [0.0]},
        ]
    )

    manifest = {
        "version": 1,
        "cogent_name": "dr.gamma",
        "dashboard": {
            "service_arn": dashboard_service_arn,
            "container_name": "web",
            "url": "https://dr-gamma.softmax-cogents.com",
        },
        "discord": {
            "service_arn": discord_service_arn,
            "container_name": "bridge",
        },
        "executor": {
            "task_definition_arn": executor_task_definition,
            "container_name": "Executor",
        },
    }

    snapshot = resolve_runtime_status(
        ecs_client=ecs_client,
        cloudwatch_client=cloudwatch_client,
        stack_name="cogent-dr-gamma-brain",
        stack_status="UPDATE_COMPLETE",
        manifest=manifest,
        existing={"certificate_arn": "arn:aws:acm:us-east-1:123456789012:certificate/abc"},
        channels={"github": "ok"},
        updated_at=123,
    )

    assert snapshot["cogent_name"] == "dr.gamma"
    assert snapshot["status_manifest"] == manifest
    assert snapshot["dashboard"]["image"].endswith(":dr-gamma-dashboard")
    assert snapshot["dashboard"]["running_count"] == 1
    assert snapshot["dashboard"]["cpu_1m"] == 17
    assert snapshot["dashboard"]["cpu_10m"] == 15
    assert snapshot["dashboard"]["mem_pct"] == 42
    assert snapshot["executor"]["image"].endswith(":executor-dr-gamma")
    assert snapshot["discord"]["image"].endswith(":discord-bridge")
    assert snapshot["image_tag"].endswith(":dr-gamma-dashboard")
    assert snapshot["dashboard_url"] == "https://dr-gamma.softmax-cogents.com"
    assert snapshot["domain"] == "dr-gamma.softmax-cogents.com"
    assert snapshot["certificate_arn"].endswith("/abc")
    assert snapshot["channels"] == {"github": "ok"}
    assert snapshot["updated_at"] == 123
    assert len(cloudwatch_client.calls) == 1
