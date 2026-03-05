"""Per-cogent dashboard stack — ALB + Fargate in the polis account."""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import Duration
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from constructs import Construct

from polis.config import PolisConfig

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent.parent)


class DashboardStack(cdk.Stack):
    """Per-cogent dashboard: ALB + Fargate service in the polis account."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: PolisConfig,
        cogent_name: str,
        certificate_arn: str,
        brain_account_id: str,
        db_cluster_arn: str,
        db_secret_arn: str,
        event_bus_name: str,
        sessions_bucket_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        safe_name = cogent_name.replace(".", "-")

        # Import existing polis ECS cluster & VPC
        vpc = ec2.Vpc.from_lookup(self, "Vpc", is_default=True)
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "Cluster",
            cluster_name="cogent-polis",
            vpc=vpc,
            security_groups=[],
        )

        # ACM certificate (already in polis account)
        certificate = acm.Certificate.from_certificate_arn(
            self, "Cert", certificate_arn
        )

        # Cross-account role ARN in the brain account
        cross_account_role_arn = (
            f"arn:aws:iam::{brain_account_id}:role/cogent-{safe_name}-dashboard-access"
        )

        # Select only one public subnet per AZ (default VPC may have extras)
        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            one_per_az=True,
        )

        # ALB (explicit subnet selection to avoid duplicate-AZ error)
        lb = elbv2.ApplicationLoadBalancer(
            self, "LB",
            vpc=vpc,
            internet_facing=True,
            vpc_subnets=public_subnets,
        )

        # Target group
        target_group = elbv2.ApplicationTargetGroup(
            self, "TG",
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

        # HTTPS listener
        lb.add_listener(
            "HttpsListener",
            port=443,
            certificates=[elbv2.ListenerCertificate.from_arn(certificate_arn)],
            default_target_groups=[target_group],
        )

        # HTTP redirect to HTTPS
        lb.add_redirect(
            source_port=80,
            target_port=443,
            target_protocol=elbv2.ApplicationProtocol.HTTPS,
        )

        # Task definition
        task_def = ecs.FargateTaskDefinition(
            self, "TaskDef",
            cpu=256,
            memory_limit_mib=512,
        )

        task_def.add_container(
            "web",
            image=ecs.ContainerImage.from_asset(
                _PROJECT_ROOT,
                file="dashboard/Dockerfile",
                platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            port_mappings=[ecs.PortMapping(container_port=5174)],
            environment={
                "COGENT_NAME": cogent_name,
                "DASHBOARD_COGENT_NAME": cogent_name,
                "DB_RESOURCE_ARN": db_cluster_arn,
                "DB_CLUSTER_ARN": db_cluster_arn,
                "DB_SECRET_ARN": db_secret_arn,
                "DB_NAME": "cogent",
                "EVENT_BUS_NAME": event_bus_name,
                "SESSIONS_BUCKET": sessions_bucket_name,
                "AWS_ROLE_ARN": cross_account_role_arn,
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="dashboard"),
        )

        # Allow the task role to assume the cross-account role
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[cross_account_role_arn],
            )
        )

        # Fargate service
        sg = ec2.SecurityGroup(self, "ServiceSg", vpc=vpc)
        sg.add_ingress_rule(
            ec2.Peer.security_group_id(lb.connections.security_groups[0].security_group_id),
            ec2.Port.tcp(5174),
        )

        service = ecs.FargateService(
            self, "Service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=True,
            security_groups=[sg],
            vpc_subnets=public_subnets,
        )

        target_group.add_target(service)

        # Outputs
        cdk.CfnOutput(self, "DashboardUrl",
                       value=f"https://{safe_name}.{config.domain}")
        cdk.CfnOutput(self, "AlbDns",
                       value=lb.load_balancer_dns_name)
