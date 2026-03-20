"""Core polis CDK stack: ECS cluster, ECR repo, Route53, DynamoDB, agent watcher Lambda."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecr as ecr,
)
from aws_cdk import (
    aws_ecr_assets,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_elasticloadbalancingv2 as elbv2,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_route53 as route53,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from constructs import Construct

from polis import naming
from polis.cdk.constructs.database import SharedDatabaseConstruct
from polis.config import PolisConfig

SRC_DIR = Path(__file__).resolve().parents[3]
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
EMAIL_HANDLER_DIR = Path(__file__).resolve().parent.parent.parent / "io" / "email"


class PolisStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: PolisConfig,
        org_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Shared VPC (default VPC, used by all constructs) ---
        self.vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # --- ECS Cluster ---
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=naming.cluster_name(),
            vpc=self.vpc,
            enable_fargate_capacity_providers=True,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # --- ECR Repository ---
        self.ecr_repo = ecr.Repository(
            self,
            "ECR",
            repository_name=naming.ecr_repo_name(),
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    description="Expire untagged images after 30 days",
                    tag_status=ecr.TagStatus.UNTAGGED,
                    max_image_age=Duration.days(30),
                ),
                ecr.LifecycleRule(
                    description="Keep last 50 images",
                    max_image_count=50,
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Allow cross-account pulls from the org
        self.ecr_repo.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowOrgPull",
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:BatchCheckLayerAvailability",
                ],
                principals=[iam.AnyPrincipal()],  # type: ignore[arg-type]
                conditions={"StringEquals": {"aws:PrincipalOrgID": org_id}},
            )
        )

        # --- Route53 Hosted Zone (import existing) ---
        self.hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "HostedZone",
            hosted_zone_id="Z059653727QDSCT3DI6DS",
            zone_name=config.domain,
        )

        # --- DynamoDB Status Table ---
        self.status_table = dynamodb.Table(
            self,
            "StatusTable",
            table_name=naming.table_name("status"),
            partition_key=dynamodb.Attribute(
                name="cogent_name",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # --- Shared Aurora Database ---
        self.database = SharedDatabaseConstruct(self, "SharedDb", vpc=self.vpc)

        # --- Shared EventBridge Bus (all cogents share one bus) ---
        self.event_bus = events.EventBus(
            self,
            "SharedEventBus",
            event_bus_name=naming.shared_event_bus_name(),
        )

        # --- Shared ALB for cogent dashboards ---
        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        self.shared_alb = elbv2.ApplicationLoadBalancer(
            self,
            "SharedALB",
            vpc=self.vpc,
            internet_facing=True,
            vpc_subnets=public_subnets,
        )

        # Wildcard cert for *.softmax-cogents.com
        wildcard_cert_arn = self.node.try_get_context("wildcard_cert_arn") or ""
        if wildcard_cert_arn:
            self.https_listener = self.shared_alb.add_listener(
                "HttpsListener",
                port=443,
                certificates=[elbv2.ListenerCertificate.from_arn(wildcard_cert_arn)],
                default_action=elbv2.ListenerAction.fixed_response(
                    status_code=404,
                    content_type="text/plain",
                    message_body="Not found",
                ),
            )

            self.shared_alb.add_redirect(
                source_port=80,
                target_port=443,
                target_protocol=elbv2.ApplicationProtocol.HTTPS,
            )
        else:
            self.https_listener = None

        # --- Agent Watcher Lambda ---
        self.watcher_fn = lambda_.Function(
            self,
            "WatcherLambda",
            function_name=naming.lambda_name("", "watcher"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="polis.watcher.handler.handler",
            code=lambda_.Code.from_asset(str(SRC_DIR)),
            timeout=Duration.seconds(120),
            environment={
                "DYNAMO_TABLE": self.status_table.table_name,
                "DB_CLUSTER_ARN": self.database.cluster_arn,
                "DB_SECRET_ARN": self.database.secret.secret_arn if self.database.secret else "",
            },
        )

        # Watcher permissions
        self.status_table.grant_read_write_data(self.watcher_fn)

        self.watcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:ListStacks",
                    "cloudformation:DescribeStacks",
                ],
                resources=["*"],
            )
        )
        self.watcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:ListServices",
                    "ecs:DescribeServices",
                    "ecs:DescribeTaskDefinition",
                    "ecs:ListClusters",
                ],
                resources=["*"],
            )
        )
        self.watcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:ListSecrets"],
                resources=["*"],
            )
        )
        self.watcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:GetMetricData"],
                resources=["*"],
            )
        )

        # Schedule: every 1 minute
        rule = events.Rule(
            self,
            "WatcherSchedule",
            schedule=events.Schedule.rate(Duration.minutes(1)),
        )
        rule.add_target(targets.LambdaFunction(self.watcher_fn))  # type: ignore[arg-type]

        # --- Polis Admin Role (assumable by any account in the org) ---
        self.admin_role = iam.Role(
            self,
            "PolisAdminRole",
            role_name=naming.iam_role_name("polis-admin"),
            assumed_by=iam.OrganizationPrincipal(org_id),  # type: ignore[arg-type]
        )

        # Route53, ACM, DynamoDB, Secrets Manager, ECS, ECR, CloudFormation
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "route53:ChangeResourceRecordSets",
                    "route53:ListResourceRecordSets",
                    "route53:GetHostedZone",
                ],
                resources=[f"arn:aws:route53:::hostedzone/{self.hosted_zone.hosted_zone_id}"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "acm:RequestCertificate",
                    "acm:DescribeCertificate",
                    "acm:DeleteCertificate",
                    "acm:ListCertificates",
                    "acm:AddTagsToCertificate",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "servicequotas:GetAWSDefaultServiceQuota",
                    "servicequotas:GetServiceQuota",
                    "servicequotas:ListRequestedServiceQuotaChangeHistoryByQuota",
                    "servicequotas:ListServiceQuotas",
                    "servicequotas:RequestServiceQuotaIncrease",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:CreateServiceLinkedRole"],
                resources=["*"],
                conditions={"StringLike": {"iam:AWSServiceName": "servicequotas.amazonaws.com"}},
            )
        )
        self.status_table.grant_read_write_data(self.admin_role)
        # Lambda — manage cogent Lambda functions (update env vars, code)
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "lambda:GetFunctionConfiguration",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:UpdateFunctionCode",
                    "lambda:ListFunctions",
                ],
                resources=["arn:aws:lambda:*:*:function:cogent-*"],
            )
        )
        # IAM — manage cogent task role policies (update DB ARNs)
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "iam:ListRolePolicies",
                    "iam:GetRolePolicy",
                    "iam:PutRolePolicy",
                ],
                resources=["arn:aws:iam::*:role/cogent-*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:CreateSecret",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:ListSecrets",
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:UpdateSecretVersionStage",
                    "secretsmanager:RotateSecret",
                ],
                resources=["*"],
            )
        )
        # SQS — manage discord reply queues and other SQS resources
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "sqs:CreateQueue",
                    "sqs:DeleteQueue",
                    "sqs:GetQueueUrl",
                    "sqs:GetQueueAttributes",
                    "sqs:ListQueues",
                    "sqs:SendMessage",
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:SetQueueAttributes",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:DescribeClusters",
                    "ecs:DescribeServices",
                    "ecs:DescribeTasks",
                    "ecs:DescribeTaskDefinition",
                    "ecs:ExecuteCommand",
                    "ecs:ListServices",
                    "ecs:ListTasks",
                    "ecs:ListTaskDefinitions",
                    "ecs:RunTask",
                    "ecs:StopTask",
                    "ecs:UpdateService",
                    "ecs:RegisterTaskDefinition",
                    "ecs:DeregisterTaskDefinition",
                    "ecr:DescribeRepositories",
                    "ecr:DescribeImages",
                    "ecr:ListImages",
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:PutImage",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                ],
                resources=["*"],
            )
        )
        # ECS service needs iam:PassRole to update task definitions
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=["*"],
                conditions={"StringLike": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )
        # RDS Data API — CLI access to cogent databases
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                    "rds-data:BeginTransaction",
                    "rds-data:CommitTransaction",
                    "rds-data:RollbackTransaction",
                ],
                resources=["*"],
            )
        )
        # CloudFormation, Lambda, RDS, ELB — read-only for status checks
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:ListStacks",
                    "cloudformation:ListStackResources",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "lambda:GetFunction",
                    "lambda:InvokeFunction",
                    "lambda:ListFunctions",
                    "lambda:UpdateFunctionCode",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:GetLogEvents",
                    "logs:FilterLogEvents",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds:DescribeDBClusters",
                    "events:ListEventBuses",
                    "events:ListRules",
                    "events:DescribeRule",
                    "events:PutEvents",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                    "elasticloadbalancing:DescribeLoadBalancers",
                    "elasticloadbalancing:DescribeTargetGroups",
                    "elasticloadbalancing:DescribeTargetHealth",
                    "ssm:StartSession",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:DescribeTable",
                    "dynamodb:Scan",
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:DeleteItem",
                ],
                resources=[self.status_table.table_arn],
            )
        )
        # RDS Data API + CloudFormation (for CLI cogtainer commands)
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                    "rds-data:BeginTransaction",
                    "rds-data:CommitTransaction",
                    "rds-data:RollbackTransaction",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:ListStackResources",
                ],
                resources=["*"],
            )
        )

        # SES — send email on behalf of cogents
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[f"arn:aws:ses:*:*:identity/{config.domain}"],
            )
        )

        # --- Email Ingest Lambda (receives from Cloudflare Email Worker) ---
        email_ingest_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "EmailIngestSecret",
            "polis/email/ingest_secret",
        )

        self.email_ingest_fn = lambda_.Function(
            self,
            "EmailIngestLambda",
            function_name=naming.lambda_name("", "email-ingest"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(EMAIL_HANDLER_DIR)),
            timeout=Duration.seconds(30),
            environment={
                "EMAIL_INGEST_SECRET": email_ingest_secret.secret_value.unsafe_unwrap(),
                "DB_CLUSTER_ARN": self.database.cluster_arn,
                "DB_SECRET_ARN": self.database.secret.secret_arn if self.database.secret else "",
                "DYNAMO_TABLE": self.status_table.table_name,
            },
        )

        # DynamoDB read access for resolving cogent db_name
        self.status_table.grant_read_data(self.email_ingest_fn)

        # RDS Data API + Secrets Manager for writing events
        self.email_ingest_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=["*"],
            )
        )
        self.email_ingest_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=["*"],
            )
        )

        # Function URL for Cloudflare Worker to POST to
        self.email_ingest_url = self.email_ingest_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # --- GitHub Actions OIDC (for CI Docker builds) ---
        github_oidc_provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOIDC",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        self.github_actions_role = iam.Role(
            self,
            "GitHubActionsRole",
            role_name="github-actions-cogents",
            assumed_by=iam.WebIdentityPrincipal(  # type: ignore[arg-type]
                github_oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": "repo:Metta-AI/cogos:*",
                    },
                },
            ),
            max_session_duration=Duration.hours(1),
        )

        self.ecr_repo.grant_pull_push(self.github_actions_role)
        self.github_actions_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )

        # --- CI Artifacts Bucket ---
        self.ci_artifacts_bucket = s3.Bucket(
            self,
            "CIArtifactsBucket",
            bucket_name=naming.polis_bucket_name("ci-artifacts"),
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-artifacts",
                    expiration=Duration.days(90),
                ),
            ],
        )
        self.ci_artifacts_bucket.grant_read_write(self.github_actions_role)
        self.ci_artifacts_bucket.grant_read(self.admin_role)

        # --- Shared Discord Reply Queue ---
        self.discord_reply_queue = sqs.Queue(
            self,
            "DiscordReplyQueue",
            queue_name=naming.queue_name("polis", "discord-replies"),
            visibility_timeout=Duration.seconds(60),
            retention_period=Duration.days(1),
        )

        # --- Outputs ---
        cdk.CfnOutput(self, "GitHubActionsRoleArn", value=self.github_actions_role.role_arn)
        cdk.CfnOutput(self, "ECRRepositoryUri", value=self.ecr_repo.repository_uri)
        cdk.CfnOutput(self, "ClusterArn", value=self.cluster.cluster_arn)
        cdk.CfnOutput(self, "HostedZoneId", value=self.hosted_zone.hosted_zone_id)
        cdk.CfnOutput(self, "Domain", value=config.domain)
        cdk.CfnOutput(self, "StatusTableArn", value=self.status_table.table_arn)
        cdk.CfnOutput(self, "PolisAdminRoleArn", value=self.admin_role.role_arn)
        cdk.CfnOutput(self, "EmailIngestUrl", value=self.email_ingest_url.url)
        cdk.CfnOutput(self, "CIArtifactsBucketName", value=self.ci_artifacts_bucket.bucket_name)
        cdk.CfnOutput(self, "DiscordReplyQueueUrl", value=self.discord_reply_queue.queue_url)
        cdk.CfnOutput(self, "SharedEventBusArn", value=self.event_bus.event_bus_arn)
        cdk.CfnOutput(self, "SharedEventBusName", value=self.event_bus.event_bus_name)
        cdk.CfnOutput(self, "SharedAlbArn", value=self.shared_alb.load_balancer_arn)
        cdk.CfnOutput(self, "SharedAlbDns", value=self.shared_alb.load_balancer_dns_name)
        if self.https_listener:
            cdk.CfnOutput(self, "SharedHttpsListenerArn", value=self.https_listener.listener_arn)
        cdk.CfnOutput(self, "SharedAlbSecurityGroupId", value=self.shared_alb.connections.security_groups[0].security_group_id)

    # TODO: Add Discord Fargate service once VPC networking is resolved.
    # For now the bridge runs locally or on existing per-cogent ECS services.
