"""Aurora Serverless v2 database construct."""

from __future__ import annotations

from aws_cdk import RemovalPolicy, aws_ec2 as ec2, aws_rds as rds
from constructs import Construct

from brain.cdk.config import BrainConfig


class DatabaseConstruct(Construct):
    """Aurora Serverless v2 PostgreSQL with Data API enabled."""

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

        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_4,
            ),
            default_database_name="cogent",
            enable_data_api=True,
            serverless_v2_min_capacity=config.db_min_acu,
            serverless_v2_max_capacity=config.db_max_acu,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
            removal_policy=RemovalPolicy.RETAIN,
            writer=rds.ClusterInstance.serverless_v2("Writer"),
        )

        self.secret = self.cluster.secret
        self.cluster_arn = self.cluster.cluster_arn
