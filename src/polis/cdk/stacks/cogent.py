"""Per-cogent CDK stack — wiring into shared polis infrastructure.

Creates: IAM role, S3 sessions bucket, SQS ingress queue, EventBridge rules,
discord reply queue access, and (optionally) a dashboard Fargate service.

Lambdas and ECS task defs are NOT created here — they are shared, versioned
by commit, and deployed by CI.  This stack only creates the per-cogent wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from polis import naming

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent.parent)


class CogentStack(Stack):
    """Per-cogent CDK stack that wires into shared polis infrastructure."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        cogent_name: str,
        domain: str,
        shared_event_bus_name: str,
        shared_db_cluster_arn: str,
        shared_db_secret_arn: str,
        shared_alb_listener_arn: str = "",
        shared_alb_security_group_id: str = "",
        certificate_arn: str = "",
        ecr_repo_uri: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        safe_name = naming.safe(cogent_name)
        db_name = f"cogent_{safe_name.replace('-', '_')}"

        self.dashboard_service: ecs.FargateService | None = None
        self.dashboard_url: str | None = None

        cdk.Tags.of(self).add("cogent_name", cogent_name)
        cdk.Tags.of(self).add("cogent_safe_name", safe_name)

        # -----------------------------------------------------------------
        # 1. Per-cogent IAM Role (assumed by shared Lambdas/ECS at runtime)
        # -----------------------------------------------------------------
        self.cogent_role = iam.Role(
            self,
            "CogentRole",
            role_name=naming.iam_role_name(safe_name),
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("lambda.amazonaws.com"),
                iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # RDS Data API
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                ],
                resources=[shared_db_cluster_arn],
            )
        )

        # Secrets Manager — shared DB secret + cogent-specific + polis secrets
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    shared_db_secret_arn,
                    f"arn:aws:secretsmanager:*:*:secret:cogent/{cogent_name}/*",
                    "arn:aws:secretsmanager:*:*:secret:cogent/polis/*",
                ],
            )
        )

        # EventBridge
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )

        # Bedrock
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:Converse",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )

        # SES
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[
                    f"arn:aws:ses:*:*:identity/{domain}",
                    "arn:aws:ses:*:*:identity/*",
                ],
            )
        )

        # Lambda InvokeFunction for this cogent's functions
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:*:*:function:{naming.lambda_name(safe_name, '*')}",
                ],
            )
        )

        # ECS RunTask + iam:PassRole
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask", "iam:PassRole"],
                resources=["*"],
            )
        )

        # SSM messages (for ECS Exec)
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )

        # STS AssumeRole for tool-specific roles
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::*:role/{naming.iam_role_name(f'{safe_name}-tool')}-*",
                ],
            )
        )

        # -----------------------------------------------------------------
        # 2. S3 Sessions Bucket (import existing bucket if it already exists)
        # -----------------------------------------------------------------
        self.sessions_bucket = s3.Bucket.from_bucket_name(
            self, "SessionsBucket", naming.bucket_name(cogent_name),
        )

        # Grant the cogent role read/write on the sessions bucket
        self.sessions_bucket.grant_read_write(self.cogent_role)

        # -----------------------------------------------------------------
        # 3. SQS FIFO Ingress Queue
        # -----------------------------------------------------------------
        self.ingress_queue = sqs.Queue(
            self,
            "CogosIngressQueue",
            queue_name=f"{naming.queue_name(safe_name, 'cogos-ingress')}.fifo",
            fifo=True,
            content_based_deduplication=False,
            visibility_timeout=Duration.seconds(60),
        )

        # Grant the cogent role send on the ingress queue
        self.ingress_queue.grant_send_messages(self.cogent_role)

        # -----------------------------------------------------------------
        # 4. EventBridge Rules on shared polis bus
        # -----------------------------------------------------------------
        shared_bus = events.EventBus.from_event_bus_name(
            self, "SharedBus", shared_event_bus_name,
        )

        # Reference existing Lambdas (deployed by CI)
        orchestrator_fn = lambda_.Function.from_function_name(
            self, "OrchestratorFn", naming.lambda_name(safe_name, "orchestrator"),
        )
        dispatcher_fn = lambda_.Function.from_function_name(
            self, "DispatcherFn", naming.lambda_name(safe_name, "dispatcher"),
        )

        # CatchAll rule: source prefix "cogent." AND detail.cogent_name matches
        events.Rule(
            self,
            "CatchAllRule",
            event_bus=shared_bus,
            rule_name=naming.rule_name(safe_name, "catch-all"),
            event_pattern=events.EventPattern(
                source=events.Match.prefix("cogent."),
                detail={"cogent_name": [cogent_name]},
            ),
            targets=[targets.LambdaFunction(orchestrator_fn)],
        )

        # Dispatcher schedule — every 1 minute
        events.Rule(
            self,
            "DispatcherSchedule",
            rule_name=naming.rule_name(safe_name, "dispatcher-schedule"),
            schedule=events.Schedule.rate(Duration.minutes(1)),
            targets=[targets.LambdaFunction(dispatcher_fn)],
        )

        # -----------------------------------------------------------------
        # 5. Discord reply queue access
        # -----------------------------------------------------------------
        polis_discord_queue = sqs.Queue.from_queue_arn(
            self,
            "PolisDiscordQueue",
            f"arn:aws:sqs:{self.region}:{self.account}:{naming.queue_name('polis', 'discord-replies')}",
        )
        polis_discord_queue.grant_send_messages(self.cogent_role)

        # -----------------------------------------------------------------
        # 6. Dashboard (optional)
        # -----------------------------------------------------------------
        if certificate_arn and shared_alb_listener_arn:
            self._create_dashboard(
                cogent_name=cogent_name,
                safe_name=safe_name,
                domain=domain,
                db_name=db_name,
                shared_db_cluster_arn=shared_db_cluster_arn,
                shared_db_secret_arn=shared_db_secret_arn,
                shared_event_bus_name=shared_event_bus_name,
                shared_alb_listener_arn=shared_alb_listener_arn,
                shared_alb_security_group_id=shared_alb_security_group_id,
            )

        # -----------------------------------------------------------------
        # Outputs
        # -----------------------------------------------------------------
        CfnOutput(self, "CogentName", value=cogent_name)
        CfnOutput(self, "CogentRoleArn", value=self.cogent_role.role_arn)
        CfnOutput(self, "SessionsBucketName", value=self.sessions_bucket.bucket_name)
        CfnOutput(self, "IngressQueueUrl", value=self.ingress_queue.queue_url)
        if self.dashboard_url:
            CfnOutput(self, "DashboardUrl", value=self.dashboard_url)
        CfnOutput(
            self,
            "StatusManifest",
            value=self.to_json_string(
                self._status_manifest(cogent_name, safe_name, domain)
            ),
        )

    # ------------------------------------------------------------------
    # Status manifest
    # ------------------------------------------------------------------
    def _status_manifest(
        self, cogent_name: str, safe_name: str, domain: str
    ) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "version": 1,
            "cogent_name": cogent_name,
        }
        if self.dashboard_service and self.dashboard_url:
            manifest["dashboard"] = {
                "service_arn": self.dashboard_service.service_arn,
                "container_name": "web",
                "url": self.dashboard_url,
            }
        else:
            manifest["dashboard"] = {
                "url": f"https://{safe_name}.{domain}",
            }
        return manifest

    # ------------------------------------------------------------------
    # Dashboard: target group + listener rule on shared ALB + Fargate
    # ------------------------------------------------------------------
    def _create_dashboard(
        self,
        *,
        cogent_name: str,
        safe_name: str,
        domain: str,
        db_name: str,
        shared_db_cluster_arn: str,
        shared_db_secret_arn: str,
        shared_event_bus_name: str,
        shared_alb_listener_arn: str,
        shared_alb_security_group_id: str,
    ) -> None:
        vpc = ec2.Vpc.from_lookup(self, "DashVpc", is_default=True)

        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "PolisCluster",
            cluster_name=naming.cluster_name(),
            vpc=vpc,
            security_groups=[],
        )

        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        # Target group on port 5174
        target_group = elbv2.ApplicationTargetGroup(
            self,
            "DashTG",
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

        # Listener rule on shared ALB (host-based routing)
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self,
            "SharedListener",
            listener_arn=shared_alb_listener_arn,
            security_group=ec2.SecurityGroup.from_security_group_id(
                self, "SharedAlbSg", shared_alb_security_group_id,
            ),
        )

        # Deterministic priority from safe_name hash
        priority = (hash(safe_name) % 49999) + 1

        elbv2.ApplicationListenerRule(
            self,
            "DashListenerRule",
            listener=listener,
            priority=priority,
            conditions=[
                elbv2.ListenerCondition.host_headers(
                    [f"{safe_name}.{domain}"]
                ),
            ],
            action=elbv2.ListenerAction.forward([target_group]),
        )

        # Task definition
        task_def = ecs.FargateTaskDefinition(
            self, "DashTaskDef", cpu=256, memory_limit_mib=512,
        )

        docker_version = (
            (Path(_PROJECT_ROOT) / "dashboard" / "DOCKER_VERSION")
            .read_text()
            .strip()
        )

        db_env = {
            "COGENT_NAME": cogent_name,
            "DASHBOARD_COGENT_NAME": cogent_name,
            "DB_RESOURCE_ARN": shared_db_cluster_arn,
            "DB_CLUSTER_ARN": shared_db_cluster_arn,
            "DB_SECRET_ARN": shared_db_secret_arn,
            "DB_NAME": db_name,
            "EVENT_BUS_NAME": shared_event_bus_name,
            "SESSIONS_BUCKET": self.sessions_bucket.bucket_name,
            "DASHBOARD_ASSETS_S3": f"s3://{self.sessions_bucket.bucket_name}/dashboard/frontend.tar.gz",
            "DASHBOARD_DOCKER_VERSION": docker_version,
            "EXECUTOR_FUNCTION_NAME": naming.lambda_name(safe_name, "executor"),
        }

        task_def.add_container(
            "web",
            image=ecs.ContainerImage.from_asset(
                _PROJECT_ROOT,
                file="dashboard/Dockerfile",
                platform=aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            port_mappings=[ecs.PortMapping(container_port=5174)],
            environment=db_env,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="dashboard"),
        )

        # Dashboard task role permissions
        task_role = task_def.task_role
        assert isinstance(task_role, iam.Role)

        # Data API
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                ],
                resources=[shared_db_cluster_arn],
            )
        )

        # Secrets
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    shared_db_secret_arn,
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:cogent/{cogent_name}/*",
                ],
            )
        )

        # Events
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )

        # Logs
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:FilterLogEvents"],
                resources=["*"],
            )
        )

        # Lambda invoke (executor)
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:*:*:function:{naming.lambda_name(safe_name, 'executor')}",
                ],
            )
        )

        # S3
        self.sessions_bucket.grant_read_write(task_role)

        # Security group — allow traffic from shared ALB
        sg = ec2.SecurityGroup(self, "DashSg", vpc=vpc)
        if shared_alb_security_group_id:
            sg.add_ingress_rule(
                ec2.Peer.security_group_id(shared_alb_security_group_id),
                ec2.Port.tcp(5174),
            )

        # Fargate service
        service = ecs.FargateService(
            self,
            "DashService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=True,
            security_groups=[sg],
            vpc_subnets=public_subnets,
        )

        target_group.add_target(service)

        self.dashboard_service = service
        self.dashboard_url = f"https://{safe_name}.{domain}"
