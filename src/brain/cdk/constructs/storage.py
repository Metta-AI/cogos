"""EFS and S3 storage constructs."""

from __future__ import annotations

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from constructs import Construct

from brain.cdk.config import BrainConfig


class StorageConstruct(Construct):
    """EFS filesystem for Claude Code sessions and program artifacts."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
    ) -> None:
        super().__init__(scope, id)

        self.filesystem = efs.FileSystem(
            self,
            "Efs",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            removal_policy=RemovalPolicy.RETAIN,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            throughput_mode=efs.ThroughputMode.ELASTIC,
        )
        # Allow ECS security group to mount EFS
        self.filesystem.connections.allow_default_port_from(security_group)

        self.access_point = self.filesystem.add_access_point(
            "CogentAp",
            path=f"/cogent/{config.cogent_name}",
            create_acl=efs.Acl(owner_uid="1000", owner_gid="1000", permissions="755"),
            posix_user=efs.PosixUser(uid="1000", gid="1000"),
        )
