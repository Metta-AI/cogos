"""Brain CDK stack — composes all constructs into a single deployable stack."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from constructs import Construct

from brain.cdk.config import BrainConfig
from brain.cdk.constructs.compute import ComputeConstruct
from brain.cdk.constructs.database import DatabaseConstruct
from brain.cdk.constructs.monitoring import MonitoringConstruct
from brain.cdk.constructs.network import NetworkConstruct
from brain.cdk.constructs.storage import StorageConstruct


class BrainStack(Stack):
    """Single CDK stack for all brain infrastructure."""

    def __init__(self, scope: Construct, id: str, *, config: BrainConfig, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        safe_name = config.cogent_name.replace(".", "-")

        # 1. Network (VPC for ECS and Aurora only — Lambdas don't need VPC)
        self.network = NetworkConstruct(self, "Network", config=config)

        # 2. Database
        self.database = DatabaseConstruct(
            self,
            "Database",
            config=config,
            vpc=self.network.vpc,
            security_group=self.network.db_sg,
        )

        # 3. Storage (EFS for ECS tasks only)
        self.storage = StorageConstruct(
            self,
            "Storage",
            config=config,
            vpc=self.network.vpc,
            security_group=self.network.ecs_sg,
        )

        # 4. EventBridge bus (created before compute so we have the name)
        self.event_bus = events.EventBus(
            self,
            "EventBus",
            event_bus_name=f"cogent-{safe_name}",
        )

        # 5. Compute (needs bus name, db ARNs, storage)
        self.compute = ComputeConstruct(
            self,
            "Compute",
            config=config,
            vpc=self.network.vpc,
            ecs_sg=self.network.ecs_sg,
            db_cluster_arn=self.database.cluster_arn,
            db_secret_arn=self.database.secret.secret_arn if self.database.secret else "",
            filesystem=self.storage.filesystem,
            access_point=self.storage.access_point,
            event_bus_name=self.event_bus.event_bus_name,
        )

        # 6. EventBridge rule (needs orchestrator from compute)
        events.Rule(
            self,
            "CatchAllRule",
            event_bus=self.event_bus,
            rule_name=f"cogent-{safe_name}-catch-all",
            event_pattern=events.EventPattern(
                source=events.Match.prefix("cogent."),
            ),
            targets=[targets.LambdaFunction(self.compute.orchestrator)],
        )

        # 7. Monitoring
        self.monitoring = MonitoringConstruct(
            self,
            "Monitoring",
            config=config,
            orchestrator_fn=self.compute.orchestrator,
            executor_fn=self.compute.executor,
        )

        # Outputs
        CfnOutput(self, "ClusterArn", value=self.database.cluster_arn)
        CfnOutput(self, "EventBusName", value=self.event_bus.event_bus_name)
        CfnOutput(self, "EcsClusterArn", value=self.compute.ecs_cluster_arn)
