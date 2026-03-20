"""Per-cogtainer CDK stack: fully isolated AWS infrastructure.

Each cogtainer gets its own Aurora, ECS, ALB, ECR, EventBridge, and DynamoDB.
Adapted from polis/cdk/stacks/core.py but scoped to a single cogtainer.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, RemovalPolicy
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam
from aws_cdk import aws_rds as rds
from aws_cdk import aws_route53 as route53
from constructs import Construct

from cogtainer.config import CogtainerEntry


class CogtainerStack(cdk.Stack):
    """Fully isolated infrastructure for a single cogtainer."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cogtainer_name: str,
        cogtainer_entry: CogtainerEntry,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        domain = cogtainer_entry.domain or ""

        cdk.Tags.of(self).add("cogtainer", cogtainer_name)

        # --- VPC (default) ---
        self.vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        # --- Aurora Serverless v2 ---
        self.db_cluster = rds.DatabaseCluster(
            self,
            "Database",
            cluster_identifier=f"cogtainer-{cogtainer_name}-db",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4,
            ),
            default_database_name="postgres",
            enable_data_api=True,
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=16.0,
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            removal_policy=RemovalPolicy.RETAIN,
            writer=rds.ClusterInstance.serverless_v2("Writer"),
        )

        # --- ECS Fargate Cluster ---
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=f"cogtainer-{cogtainer_name}",
            vpc=self.vpc,
            enable_fargate_capacity_providers=True,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # --- ECR Repository ---
        self.ecr_repo = ecr.Repository(
            self,
            "ECR",
            repository_name=f"cogtainer-{cogtainer_name}",
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

        # --- EventBridge Bus ---
        self.event_bus = events.EventBus(
            self,
            "EventBus",
            event_bus_name=f"cogtainer-{cogtainer_name}",
        )

        # --- DynamoDB Status Table ---
        self.status_table = dynamodb.Table(
            self,
            "StatusTable",
            table_name=f"cogtainer-{cogtainer_name}-status",
            partition_key=dynamodb.Attribute(
                name="cogent_name",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- ALB ---
        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "ALB",
            vpc=self.vpc,
            internet_facing=True,
            vpc_subnets=public_subnets,
        )

        # Allow ALB to forward traffic to dashboard containers on port 5174
        self.alb.connections.security_groups[0].add_egress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(5174),
            "Allow ALB to reach dashboard containers",
        )

        # HTTPS listener with wildcard cert (if domain configured)
        wildcard_cert_arn = self.node.try_get_context("wildcard_cert_arn") or ""
        if wildcard_cert_arn:
            self.https_listener = self.alb.add_listener(
                "HttpsListener",
                port=443,
                certificates=[
                    elbv2.ListenerCertificate.from_arn(wildcard_cert_arn)
                ],
                default_action=elbv2.ListenerAction.fixed_response(
                    status_code=404,
                    content_type="text/plain",
                    message_body="Not found",
                ),
            )

            self.alb.add_redirect(
                source_port=80,
                target_port=443,
                target_protocol=elbv2.ApplicationProtocol.HTTPS,
            )
        else:
            self.https_listener = None

        # --- Route53 Hosted Zone (if domain configured) ---
        self.hosted_zone = None
        hosted_zone_id = self.node.try_get_context("hosted_zone_id") or ""
        if domain and hosted_zone_id:
            self.hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
                self,
                "HostedZone",
                hosted_zone_id=hosted_zone_id,
                zone_name=domain,
            )

        # --- Grant existing roles access to cogtainer resources ---
        for role_id, role_name in [
            ("AdminRole", self.node.try_get_context("admin_role_name") or "cogent-polis-admin"),
            ("CIRole", self.node.try_get_context("ci_role_name") or "github-actions-cogents"),
        ]:
            try:
                role = iam.Role.from_role_name(self, role_id, role_name, mutable=True)
                self.status_table.grant_read_write_data(role)
                self.db_cluster.grant_data_api_access(role)
                self.ecr_repo.grant_pull_push(role)
            except Exception:
                pass  # role may not exist yet on first deploy

        # --- Outputs ---
        CfnOutput(self, "CogtainerName", value=cogtainer_name)
        CfnOutput(self, "DbClusterArn", value=self.db_cluster.cluster_arn)
        if self.db_cluster.secret:
            CfnOutput(
                self, "DbSecretArn", value=self.db_cluster.secret.secret_arn
            )
        CfnOutput(self, "ClusterArn", value=self.cluster.cluster_arn)
        CfnOutput(self, "ECRRepositoryUri", value=self.ecr_repo.repository_uri)
        CfnOutput(self, "EventBusArn", value=self.event_bus.event_bus_arn)
        CfnOutput(self, "EventBusName", value=self.event_bus.event_bus_name)
        CfnOutput(self, "StatusTableArn", value=self.status_table.table_arn)
        CfnOutput(
            self, "StatusTableName", value=self.status_table.table_name
        )
        CfnOutput(self, "AlbArn", value=self.alb.load_balancer_arn)
        CfnOutput(self, "AlbDns", value=self.alb.load_balancer_dns_name)
        if self.https_listener:
            CfnOutput(
                self,
                "HttpsListenerArn",
                value=self.https_listener.listener_arn,
            )
        CfnOutput(
            self,
            "AlbSecurityGroupId",
            value=self.alb.connections.security_groups[0].security_group_id,
        )
        if domain:
            CfnOutput(self, "Domain", value=domain)
        if self.hosted_zone:
            CfnOutput(
                self, "HostedZoneId", value=self.hosted_zone.hosted_zone_id
            )
