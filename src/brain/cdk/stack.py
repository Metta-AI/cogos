"""Brain CDK stack — all per-cogent infrastructure in the polis account.

Includes: database, lambdas, ECS tasks, storage, events, monitoring, dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from brain.cdk.config import BrainConfig
from brain.cdk.constructs.compute import ComputeConstruct
from brain.cdk.constructs.database import DatabaseConstruct
from brain.cdk.constructs.monitoring import MonitoringConstruct
from brain.cdk.constructs.storage import StorageConstruct

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)


class BrainStack(Stack):
    """Single CDK stack for all per-cogent infrastructure (deployed in polis account)."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
        certificate_arn: str = "",
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        safe_name = config.cogent_name.replace(".", "-")
        self.dashboard_service: ecs.FargateService | None = None
        self.dashboard_url: str | None = None
        self.discord_service: ecs.FargateService | None = None
        cdk.Tags.of(self).add("cogent_name", config.cogent_name)
        cdk.Tags.of(self).add("cogent_safe_name", safe_name)

        # 1. Database (Aurora Serverless v2 in default VPC)
        self.database = DatabaseConstruct(self, "Database", config=config)

        # 2. Storage (S3 bucket for sessions)
        self.storage = StorageConstruct(self, "Storage", config=config)

        # 3. EventBridge bus
        self.event_bus = events.EventBus(
            self,
            "EventBus",
            event_bus_name=f"cogent-{safe_name}",
        )

        # 4. Compute (Lambdas outside VPC, ECS task def for shared cluster)
        self.compute = ComputeConstruct(
            self,
            "Compute",
            config=config,
            db_cluster_arn=self.database.cluster_arn,
            db_secret_arn=self.database.secret.secret_arn if self.database.secret else "",
            sessions_bucket=self.storage.bucket,
            event_bus_name=self.event_bus.event_bus_name,
        )

        # 5. EventBridge rules
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

        # Dispatcher schedule — polls proposed events every minute
        events.Rule(
            self,
            "DispatcherSchedule",
            rule_name=f"cogent-{safe_name}-dispatcher-schedule",
            schedule=events.Schedule.rate(Duration.minutes(1)),
            targets=[targets.LambdaFunction(self.compute.dispatcher)],
        )

        # 6. Monitoring
        self.monitoring = MonitoringConstruct(
            self,
            "Monitoring",
            config=config,
            orchestrator_fn=self.compute.orchestrator,
            executor_fn=self.compute.executor,
        )

        # 7. Discord bridge (Fargate on shared cogent-polis cluster)
        self._create_discord_bridge(config, safe_name)

        # Pass Discord reply queue URL to executor Lambda for cogos discord capability
        self.compute.executor.add_environment(
            "DISCORD_REPLY_QUEUE_URL", self.discord_reply_queue.queue_url,
        )

        # 8. Dashboard (ALB + Fargate on shared cogent-polis cluster)
        if certificate_arn:
            self._create_dashboard(config, safe_name, certificate_arn)

        # Outputs
        CfnOutput(self, "CogentName", value=config.cogent_name)
        CfnOutput(self, "ClusterArn", value=self.database.cluster_arn)
        if self.database.secret:
            CfnOutput(self, "SecretArn", value=self.database.secret.secret_arn)
        CfnOutput(self, "EventBusName", value=self.event_bus.event_bus_name)
        CfnOutput(self, "SessionsBucket", value=self.storage.bucket.bucket_name)
        CfnOutput(
            self,
            "StatusManifest",
            value=self.to_json_string(self._status_manifest(config, safe_name)),
        )

    def _status_manifest(self, config: BrainConfig, safe_name: str) -> dict[str, Any]:
        """Return the canonical status manifest for watcher/runtime resolution."""
        assert self.discord_service is not None
        manifest: dict[str, Any] = {
            "version": 1,
            "cogent_name": config.cogent_name,
            "discord": {
                "service_arn": self.discord_service.service_arn,
                "container_name": "bridge",
            },
            "executor": {
                "task_definition_arn": self.compute.task_definition.task_definition_arn,
                "container_name": "Executor",
            },
        }
        if self.dashboard_service and self.dashboard_url:
            manifest["dashboard"] = {
                "service_arn": self.dashboard_service.service_arn,
                "container_name": "web",
                "url": self.dashboard_url,
            }
        else:
            manifest["dashboard"] = {
                "url": f"https://{safe_name}.{config.domain}",
            }
        return manifest

    def _create_discord_bridge(self, config: BrainConfig, safe_name: str) -> None:
        """Create the Discord bridge SQS queue + Fargate service."""
        vpc = ec2.Vpc.from_lookup(self, "DiscordVpc", is_default=True)
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "DiscordPolisCluster",
            cluster_name="cogent-polis",
            vpc=vpc,
            security_groups=[],
        )

        # SQS queue for outbound replies (capability → bridge → Discord)
        self.discord_reply_queue = sqs.Queue(
            self,
            "DiscordReplyQueue",
            queue_name=f"cogent-{safe_name}-discord-replies",
            visibility_timeout=Duration.seconds(60),
            retention_period=Duration.days(1),
        )

        # Bot token from Secrets Manager (existing secret stores {"access_token": "..."})
        bot_token_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "DiscordBotToken",
            secret_name=f"cogent/{config.cogent_name}/discord",
        )

        # Task definition
        task_def = ecs.FargateTaskDefinition(
            self, "DiscordTaskDef",
            family=f"cogent-{safe_name}-discord",
            cpu=256,
            memory_limit_mib=512,
        )

        task_def.add_container(
            "bridge",
            image=ecs.ContainerImage.from_asset(
                _PROJECT_ROOT,
                file="src/cogos/io/discord/Dockerfile",
                platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            environment={
                "COGENT_NAME": config.cogent_name,
                "DB_RESOURCE_ARN": self.database.cluster_arn,
                "DB_SECRET_ARN": self.database.secret.secret_arn if self.database.secret else "",
                "DB_NAME": "cogent",
                "DISCORD_REPLY_QUEUE_URL": self.discord_reply_queue.queue_url,
                "AWS_REGION": config.region,
            },
            secrets={
                "DISCORD_BOT_TOKEN": ecs.Secret.from_secrets_manager(bot_token_secret, field="access_token"),
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="discord-bridge"),
        )

        # IAM: DB Data API
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[self.database.cluster_arn],
            )
        )
        if self.database.secret:
            task_def.task_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[self.database.secret.secret_arn],
                )
            )

        # IAM: SQS reply queue (receive for polling, send for capability)
        self.discord_reply_queue.grant_consume_messages(task_def.task_role)

        # Grant the executor/orchestrator lambdas permission to send to the reply queue
        self.discord_reply_queue.grant_send_messages(self.compute.orchestrator)
        self.discord_reply_queue.grant_send_messages(self.compute.executor)

        # Also grant the ECS executor task role send access
        self.discord_reply_queue.grant_send_messages(
            self.compute.task_definition.task_role
        )

        # Fargate service (starts with 0 desired — use CLI to start)
        sg = ec2.SecurityGroup(self, "DiscordSg", vpc=vpc, allow_all_outbound=True)

        self.discord_service = ecs.FargateService(
            self, "DiscordService",
            service_name=f"cogent-{safe_name}-discord",
            cluster=cluster,
            task_definition=task_def,
            desired_count=0,
            assign_public_ip=True,
            security_groups=[sg],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC,
                one_per_az=True,
            ),
        )

        CfnOutput(self, "DiscordReplyQueueUrl", value=self.discord_reply_queue.queue_url)

    def _create_dashboard(
        self, config: BrainConfig, safe_name: str, certificate_arn: str
    ) -> None:
        """Create the dashboard ALB + Fargate service."""
        vpc = ec2.Vpc.from_lookup(self, "DashVpc", is_default=True)
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "PolisCluster",
            cluster_name="cogent-polis",
            vpc=vpc,
            security_groups=[],
        )

        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        # ALB
        lb = elbv2.ApplicationLoadBalancer(
            self, "DashLB",
            vpc=vpc,
            internet_facing=True,
            vpc_subnets=public_subnets,
        )

        target_group = elbv2.ApplicationTargetGroup(
            self, "DashTG",
            vpc=vpc,
            port=5174,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/healthz",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
            ),
        )

        # HTTPS listener — auth handled by Cloudflare Access upstream
        lb.add_listener(
            "HttpsListener",
            port=443,
            certificates=[elbv2.ListenerCertificate.from_arn(certificate_arn)],
            default_action=elbv2.ListenerAction.forward([target_group]),
        )

        lb.add_redirect(
            source_port=80,
            target_port=443,
            target_protocol=elbv2.ApplicationProtocol.HTTPS,
        )

        # Task definition — same account, direct access to DB via Data API
        task_def = ecs.FargateTaskDefinition(self, "DashTaskDef", cpu=256, memory_limit_mib=512)
        docker_version = (
            Path(__file__).resolve().parent.parent.parent.parent / "dashboard" / "DOCKER_VERSION"
        ).read_text().strip()

        db_env = {
            "COGENT_NAME": config.cogent_name,
            "DASHBOARD_COGENT_NAME": config.cogent_name,
            "DB_RESOURCE_ARN": self.database.cluster_arn,
            "DB_CLUSTER_ARN": self.database.cluster_arn,
            "DB_SECRET_ARN": self.database.secret.secret_arn if self.database.secret else "",
            "DB_NAME": "cogent",
            "EVENT_BUS_NAME": self.event_bus.event_bus_name,
            "SESSIONS_BUCKET": self.storage.bucket.bucket_name,
            "DASHBOARD_ASSETS_S3": f"s3://{self.storage.bucket.bucket_name}/dashboard/frontend.tar.gz",
            "DASHBOARD_DOCKER_VERSION": docker_version,
        }

        task_def.add_container(
            "web",
            image=ecs.ContainerImage.from_asset(
                _PROJECT_ROOT,
                file="dashboard/Dockerfile",
                platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            port_mappings=[ecs.PortMapping(container_port=5174)],
            environment=db_env,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="dashboard"),
        )

        # Grant dashboard task role Data API access
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[self.database.cluster_arn],
            )
        )
        if self.database.secret:
            task_def.task_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[self.database.secret.secret_arn],
                )
            )
        # Allow reading dashboard API key for admin endpoint auth
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[f"arn:aws:secretsmanager:{config.region}:{config.account}:secret:cogent/{config.cogent_name}/dashboard-api-key-*"],
            )
        )
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[f"arn:aws:secretsmanager:{config.region}:{config.account}:secret:cogent/{config.cogent_name}/discord-*"],
            )
        )
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:DescribeServices"],
                resources=["*"],
            )
        )
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:FilterLogEvents"],
                resources=["*"],
            )
        )
        self.storage.bucket.grant_read_write(task_def.task_role)

        # Fargate service
        sg = ec2.SecurityGroup(self, "DashSg", vpc=vpc)
        sg.add_ingress_rule(
            ec2.Peer.security_group_id(lb.connections.security_groups[0].security_group_id),
            ec2.Port.tcp(5174),
        )

        service = ecs.FargateService(
            self, "DashService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=True,
            security_groups=[sg],
            vpc_subnets=public_subnets,
        )

        target_group.add_target(service)

        self.dashboard_service = service
        self.dashboard_url = f"https://{safe_name}.{config.domain}"
        CfnOutput(self, "DashboardUrl", value=self.dashboard_url)
        CfnOutput(self, "AlbDns", value=lb.load_balancer_dns_name)
