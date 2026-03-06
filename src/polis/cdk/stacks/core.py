"""Core polis CDK stack: ECS cluster, ECR repo, Route53, DynamoDB, agent watcher Lambda."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_route53 as route53,
)
from constructs import Construct

from polis.config import PolisConfig

WATCHER_HANDLER_DIR = Path(__file__).resolve().parent.parent.parent / "watcher"


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

        # --- ECS Cluster ---
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name="cogent-polis",
            enable_fargate_capacity_providers=True,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # --- ECR Repository ---
        self.ecr_repo = ecr.Repository(
            self,
            "ECR",
            repository_name="cogent",
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
                principals=[iam.AnyPrincipal()],
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
            table_name="cogent-status",
            partition_key=dynamodb.Attribute(
                name="cogent_name",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # --- Agent Watcher Lambda ---
        self.watcher_fn = lambda_.Function(
            self,
            "WatcherLambda",
            function_name="cogent-watcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(WATCHER_HANDLER_DIR)),
            timeout=Duration.seconds(120),
            environment={
                "DYNAMO_TABLE": self.status_table.table_name,
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
        rule.add_target(targets.LambdaFunction(self.watcher_fn))

        # --- Polis Admin Role (assumable by any account in the org) ---
        self.admin_role = iam.Role(
            self,
            "PolisAdminRole",
            role_name="cogent-polis-admin",
            assumed_by=iam.OrganizationPrincipal(org_id),
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
        self.status_table.grant_read_write_data(self.admin_role)
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
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:DescribeClusters",
                    "ecs:DescribeServices",
                    "ecs:ListServices",
                    "ecs:UpdateService",
                    "ecs:DescribeTaskDefinition",
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
                    "lambda:ListFunctions",
                    "lambda:UpdateFunctionCode",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds:DescribeDBClusters",
                ],
                resources=["*"],
            )
        )
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "elasticloadbalancing:DescribeLoadBalancers",
                    "elasticloadbalancing:DescribeTargetGroups",
                    "elasticloadbalancing:DescribeTargetHealth",
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
        # RDS Data API + CloudFormation (for CLI mind/brain commands)
        self.admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
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

        # --- Outputs ---
        cdk.CfnOutput(self, "ECRRepositoryUri", value=self.ecr_repo.repository_uri)
        cdk.CfnOutput(self, "ClusterArn", value=self.cluster.cluster_arn)
        cdk.CfnOutput(self, "HostedZoneId", value=self.hosted_zone.hosted_zone_id)
        cdk.CfnOutput(self, "Domain", value=config.domain)
        cdk.CfnOutput(self, "StatusTableArn", value=self.status_table.table_arn)
        cdk.CfnOutput(self, "PolisAdminRoleArn", value=self.admin_role.role_arn)
