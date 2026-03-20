"""Per-cogent CDK stack within a cogtainer.

Creates: IAM role, S3 sessions bucket, SQS FIFO ingress queue,
EventBridge rules, Lambdas (event-router, executor, dispatcher, ingress),
and (optionally) a dashboard Fargate service.

CDK stack for a single cogent with cogtainer-scoped naming.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from cogtainer import naming

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent.parent)


def _lambda_name(cogtainer_name: str, cogent_name: str, fn_type: str) -> str:
    """Build a Lambda function name scoped to cogtainer + cogent."""
    return f"cogtainer-{cogtainer_name}-{cogent_name}-{fn_type}"


class CogentStack(Stack):
    """Per-cogent CDK stack within a cogtainer."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        cogtainer_name: str,
        cogent_name: str,
        domain: str,
        event_bus_name: str,
        db_cluster_arn: str,
        db_secret_arn: str,
        alb_listener_arn: str = "",
        alb_security_group_id: str = "",
        certificate_arn: str = "",
        ecr_repo_uri: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        safe_name = naming.safe(cogent_name)
        db_name = f"cogent_{safe_name.replace('-', '_')}"

        self.dashboard_service: ecs.FargateService | None = None
        self.dashboard_url: str | None = None

        cdk.Tags.of(self).add("cogtainer", cogtainer_name)
        cdk.Tags.of(self).add("cogent_name", cogent_name)
        cdk.Tags.of(self).add("cogent_safe_name", safe_name)

        # -----------------------------------------------------------------
        # 1. Per-cogent IAM Role
        # -----------------------------------------------------------------
        role_name = f"cogtainer-{cogtainer_name}-{safe_name}"
        self.cogent_role = iam.Role(
            self,
            "CogentRole",
            role_name=role_name,
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
                resources=[db_cluster_arn],
            )
        )

        # Secrets Manager — DB secret + cogent-specific secrets
        self.cogent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    db_secret_arn,
                    f"arn:aws:secretsmanager:*:*:secret:cogent/{cogent_name}/*",
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

        # SES (if domain configured)
        if domain:
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
                    f"arn:aws:lambda:*:*:function:{_lambda_name(cogtainer_name, safe_name, '*')}",
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
                    f"arn:aws:iam::*:role/cogtainer-{cogtainer_name}-{safe_name}-tool-*",
                ],
            )
        )

        # -----------------------------------------------------------------
        # 2. S3 Sessions Bucket
        # -----------------------------------------------------------------
        bucket_name = f"cogtainer-{cogtainer_name}-{safe_name}-sessions"
        self.sessions_bucket = s3.Bucket(
            self,
            "SessionsBucket",
            bucket_name=bucket_name,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
        )
        self.sessions_bucket.grant_read_write(self.cogent_role)

        # -----------------------------------------------------------------
        # 3. SQS FIFO Ingress Queue
        # -----------------------------------------------------------------
        queue_base = f"cogtainer-{cogtainer_name}-{safe_name}-cogos-ingress"
        self.ingress_queue = sqs.Queue(
            self,
            "CogosIngressQueue",
            queue_name=f"{queue_base}.fifo",
            fifo=True,
            content_based_deduplication=False,
            visibility_timeout=Duration.seconds(60),
        )

        # Grant the cogent role send on the ingress queue
        self.ingress_queue.grant_send_messages(self.cogent_role)

        # -----------------------------------------------------------------
        # 4. Lambda Functions + EventBridge Rules
        # -----------------------------------------------------------------
        bus = events.EventBus.from_event_bus_name(
            self, "CogtainerBus", event_bus_name,
        )

        # Lambda code — from S3 (CI uploads) or inline placeholder
        lambda_s3_bucket = self.node.try_get_context("lambda_s3_bucket") or ""
        lambda_s3_key = self.node.try_get_context("lambda_s3_key") or ""

        if lambda_s3_bucket and lambda_s3_key:
            code = lambda_.Code.from_bucket(
                s3.Bucket.from_bucket_name(self, "LambdaBucket", lambda_s3_bucket),
                lambda_s3_key,
            )
        else:
            # Placeholder code — CI will update via cogtainer update --lambdas
            code = lambda_.Code.from_inline(
                "def handler(event, context): return {'statusCode': 200, 'body': 'not deployed yet'}"
            )

        lambda_env = {
            "COGENT_NAME": cogent_name,
            "COGTAINER_NAME": cogtainer_name,
            "DB_RESOURCE_ARN": db_cluster_arn,
            "DB_CLUSTER_ARN": db_cluster_arn,
            "DB_SECRET_ARN": db_secret_arn,
            "DB_NAME": db_name,
            "EVENT_BUS_NAME": event_bus_name,
            "SESSIONS_BUCKET": bucket_name,
        }

        # Create Lambda functions
        event_router_fn = lambda_.Function(
            self, "EventRouterFn",
            function_name=_lambda_name(cogtainer_name, safe_name, "event-router"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.orchestrator.handler.handler",
            code=code,
            role=self.cogent_role,
            timeout=Duration.seconds(60),
            memory_size=256,
            environment=lambda_env,
        )

        executor_fn = lambda_.Function(
            self, "ExecutorFn",
            function_name=_lambda_name(cogtainer_name, safe_name, "executor"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogos.executor.handler.handler",
            code=code,
            role=self.cogent_role,
            timeout=Duration.seconds(900),
            memory_size=512,
            environment={
                **lambda_env,
                "EXECUTOR_FUNCTION_NAME": _lambda_name(cogtainer_name, safe_name, "executor"),
            },
        )

        dispatcher_fn = lambda_.Function(
            self, "DispatcherFn",
            function_name=_lambda_name(cogtainer_name, safe_name, "dispatcher"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.dispatcher.handler.handler",
            code=code,
            role=self.cogent_role,
            timeout=Duration.seconds(60),
            memory_size=256,
            environment={
                **lambda_env,
                "EXECUTOR_FUNCTION_NAME": _lambda_name(cogtainer_name, safe_name, "executor"),
            },
        )

        # CatchAll rule: source prefix "cogent." AND detail.cogent_name matches
        events.Rule(
            self,
            "CatchAllRule",
            event_bus=bus,
            rule_name=f"cogtainer-{cogtainer_name}-{safe_name}-catch-all",
            event_pattern=events.EventPattern(
                source=events.Match.prefix("cogent."),
                detail={"cogent_name": [cogent_name]},
            ),
            targets=[targets.LambdaFunction(event_router_fn)],
        )

        # Dispatcher schedule — every 1 minute
        events.Rule(
            self,
            "DispatcherSchedule",
            rule_name=f"cogtainer-{cogtainer_name}-{safe_name}-dispatcher-schedule",
            schedule=events.Schedule.rate(Duration.minutes(1)),
            targets=[targets.LambdaFunction(dispatcher_fn)],
        )

        # -----------------------------------------------------------------
        # 5. Dashboard (optional)
        # -----------------------------------------------------------------
        if certificate_arn and alb_listener_arn:
            self._create_dashboard(
                cogtainer_name=cogtainer_name,
                cogent_name=cogent_name,
                safe_name=safe_name,
                domain=domain,
                db_name=db_name,
                bucket_name=bucket_name,
                db_cluster_arn=db_cluster_arn,
                db_secret_arn=db_secret_arn,
                event_bus_name=event_bus_name,
                alb_listener_arn=alb_listener_arn,
                alb_security_group_id=alb_security_group_id,
            )

        # -----------------------------------------------------------------
        # 6. Discord Bridge (Fargate service)
        # -----------------------------------------------------------------
        self._create_discord_bridge(
            cogtainer_name=cogtainer_name,
            cogent_name=cogent_name,
            safe_name=safe_name,
            db_cluster_arn=db_cluster_arn,
            db_secret_arn=db_secret_arn,
            db_name=db_name,
            bucket_name=bucket_name,
            event_bus_name=event_bus_name,
            ecr_repo_uri=ecr_repo_uri,
        )

        # -----------------------------------------------------------------
        # Outputs
        # -----------------------------------------------------------------
        CfnOutput(self, "CogtainerName", value=cogtainer_name)
        CfnOutput(self, "CogentName", value=cogent_name)
        CfnOutput(self, "CogentRoleArn", value=self.cogent_role.role_arn)
        CfnOutput(self, "DbClusterArn", value=db_cluster_arn)
        CfnOutput(self, "DbSecretArn", value=db_secret_arn)
        CfnOutput(
            self, "SessionsBucketName", value=self.sessions_bucket.bucket_name
        )
        CfnOutput(self, "IngressQueueUrl", value=self.ingress_queue.queue_url)
        if self.dashboard_url:
            CfnOutput(self, "DashboardUrl", value=self.dashboard_url)

    # ------------------------------------------------------------------
    # Dashboard: target group + listener rule on ALB + Fargate
    # ------------------------------------------------------------------
    def _create_dashboard(
        self,
        *,
        cogtainer_name: str,
        cogent_name: str,
        safe_name: str,
        domain: str,
        db_name: str,
        bucket_name: str,
        db_cluster_arn: str,
        db_secret_arn: str,
        event_bus_name: str,
        alb_listener_arn: str,
        alb_security_group_id: str,
    ) -> None:
        vpc = ec2.Vpc.from_lookup(self, "DashVpc", is_default=True)

        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "CogtainerCluster",
            cluster_name=f"cogtainer-{cogtainer_name}",
            vpc=vpc,
            security_groups=[],
        )

        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        # Target group on port 5174 (Next.js frontend, proxies /healthz to backend)
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
                interval=Duration.seconds(10),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
        )

        # Listener rule on ALB (host-based routing)
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self,
            "AlbListener",
            listener_arn=alb_listener_arn,
            security_group=ec2.SecurityGroup.from_security_group_id(
                self, "AlbSg", alb_security_group_id,
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

        # Grant ECR pull to execution role (needed for private ECR images)
        task_def.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                resources=["*"],
            )
        )

        docker_version = (
            (Path(_PROJECT_ROOT) / "dashboard" / "DOCKER_VERSION")
            .read_text()
            .strip()
        )

        db_env = {
            # HOSTNAME must be explicit — ECS overrides Dockerfile ENV with task hostname
            "HOSTNAME": "0.0.0.0",
            "PORT": "5174",
            "COGENT_NAME": cogent_name,
            "COGTAINER_NAME": cogtainer_name,
            "DASHBOARD_COGENT_NAME": cogent_name,
            "DB_RESOURCE_ARN": db_cluster_arn,
            "DB_CLUSTER_ARN": db_cluster_arn,
            "DB_SECRET_ARN": db_secret_arn,
            "DB_NAME": db_name,
            "EVENT_BUS_NAME": event_bus_name,
            "SESSIONS_BUCKET": bucket_name,
            "DASHBOARD_ASSETS_S3": f"s3://{bucket_name}/dashboard/frontend.tar.gz",
            "DASHBOARD_DOCKER_VERSION": docker_version,
            "EXECUTOR_FUNCTION_NAME": _lambda_name(
                cogtainer_name, safe_name, "executor"
            ),
        }

        # Use CI-built dashboard image from cogtainer ECR
        dash_image_tag = self.node.try_get_context("dashboard_image_tag") or "dashboard-latest"
        if ecr_repo_uri:
            dash_image = ecs.ContainerImage.from_registry(f"{ecr_repo_uri}:{dash_image_tag}")
        else:
            dash_image = ecs.ContainerImage.from_registry(
                f"{self.account}.dkr.ecr.{self.region}.amazonaws.com/cogtainer-{cogtainer_name}:{dash_image_tag}"
            )

        task_def.add_container(
            "web",
            image=dash_image,
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
                resources=[db_cluster_arn],
            )
        )

        # Secrets
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    db_secret_arn,
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
                    f"arn:aws:lambda:*:*:function:{_lambda_name(cogtainer_name, safe_name, 'executor')}",
                ],
            )
        )

        # S3
        self.sessions_bucket.grant_read_write(task_role)

        # Security group — allow traffic from ALB (app + health check ports)
        sg = ec2.SecurityGroup(self, "DashSg", vpc=vpc)
        if alb_security_group_id:
            sg.add_ingress_rule(
                ec2.Peer.security_group_id(alb_security_group_id),
                ec2.Port.tcp(5174),
                "ALB to Next.js frontend",
            )
            sg.add_ingress_rule(
                ec2.Peer.security_group_id(alb_security_group_id),
                ec2.Port.tcp(8100),
                "ALB health check to backend",
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

    # ------------------------------------------------------------------
    # Discord Bridge: Fargate service running the discord-bridge process
    # ------------------------------------------------------------------
    def _create_discord_bridge(
        self,
        *,
        cogtainer_name: str,
        cogent_name: str,
        safe_name: str,
        db_cluster_arn: str,
        db_secret_arn: str,
        db_name: str,
        bucket_name: str,
        event_bus_name: str,
        ecr_repo_uri: str,
    ) -> None:
        vpc = ec2.Vpc.from_lookup(self, "BridgeVpc", is_default=True)

        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "BridgeCluster",
            cluster_name=f"cogtainer-{cogtainer_name}",
            vpc=vpc,
            security_groups=[],
        )

        # Task definition — execution role needs ECR pull access for private images
        bridge_task_def = ecs.FargateTaskDefinition(
            self, "BridgeTaskDef", cpu=256, memory_limit_mib=512,
        )

        # Grant ECR pull to execution role
        bridge_task_def.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                resources=["*"],
            )
        )

        # Use the executor image from ECR (same codebase)
        image_tag = self.node.try_get_context("bridge_image_tag") or "executor-latest"
        if ecr_repo_uri:
            image = ecs.ContainerImage.from_registry(f"{ecr_repo_uri}:{image_tag}")
        else:
            image = ecs.ContainerImage.from_registry(
                f"{self.account}.dkr.ecr.{self.region}.amazonaws.com/cogtainer-{cogtainer_name}:{image_tag}"
            )

        # SQS queue for executor -> bridge reply messages
        replies_queue = sqs.Queue(
            self,
            "DiscordRepliesQueue",
            queue_name=f"cogent-{safe_name}-discord-replies",
            visibility_timeout=Duration.seconds(30),
        )

        bridge_env = {
            "COGENT_NAME": cogent_name,
            "COGTAINER_NAME": cogtainer_name,
            "DYNAMO_TABLE": f"cogtainer-{cogtainer_name}-status",
            "DB_RESOURCE_ARN": db_cluster_arn,
            "DB_CLUSTER_ARN": db_cluster_arn,
            "DB_SECRET_ARN": db_secret_arn,
            "DB_NAME": db_name,
            "EVENT_BUS_NAME": event_bus_name,
            "SESSIONS_BUCKET": bucket_name,
            "EXECUTOR_FUNCTION_NAME": _lambda_name(cogtainer_name, safe_name, "executor"),
            "DISCORD_REPLY_QUEUE_URL": replies_queue.queue_url,
        }

        bridge_task_def.add_container(
            "bridge",
            image=image,
            command=["python", "-m", "cogos.io.discord.bridge"],
            environment=bridge_env,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="discord-bridge"),
        )

        # Bridge task role permissions
        bridge_role = bridge_task_def.task_role
        assert isinstance(bridge_role, iam.Role)

        # RDS Data API
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[db_cluster_arn],
            )
        )

        # Secrets Manager — DB secret + cogent discord secrets + shared discord secret
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    db_secret_arn,
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:cogent/{cogent_name}/*",
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:agora/*",
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:cogtainer/*",
                ],
            )
        )

        # DynamoDB — read cogent-status table for config
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Scan", "dynamodb:GetItem"],
                resources=[
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/cogtainer-{cogtainer_name}-status",
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/cogent-status",
                ],
            )
        )

        # EventBridge
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )

        # Lambda invoke (executor)
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:*:*:function:{_lambda_name(cogtainer_name, safe_name, '*')}",
                ],
            )
        )

        # SQS — ingress queue
        self.ingress_queue.grant_send_messages(bridge_role)

        # SQS — replies queue (bridge receives, executor sends)
        replies_queue.grant_consume_messages(bridge_role)
        replies_queue.grant_send_messages(self.cogent_role)

        # S3
        bridge_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"arn:aws:s3:::{bucket_name}/*"],
            )
        )

        # Fargate service (desired_count=1 to start)
        ecs.FargateService(
            self,
            "BridgeService",
            service_name=f"cogtainer-{cogtainer_name}-{safe_name}-discord",
            cluster=cluster,
            task_definition=bridge_task_def,
            desired_count=1,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC, one_per_az=True,
            ),
        )
