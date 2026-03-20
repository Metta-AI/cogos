"""Shared Aurora Serverless v2 database for all cogent databases."""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct


class SharedDatabaseConstruct(Construct):
    """Single Aurora Serverless v2 PostgreSQL cluster shared by all cogents.

    Each cogent gets its own database on this cluster. All access is via
    the RDS Data API.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        vpc: ec2.IVpc,
        min_acu: float = 0.5,
        max_acu: float = 16.0,
    ) -> None:
        super().__init__(scope, id)

        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4,
            ),
            default_database_name="postgres",
            enable_data_api=True,
            serverless_v2_min_capacity=min_acu,
            serverless_v2_max_capacity=max_acu,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            removal_policy=RemovalPolicy.RETAIN,
            writer=rds.ClusterInstance.serverless_v2("Writer"),
        )

        self.secret = self.cluster.secret
        self.cluster_arn = self.cluster.cluster_arn

        CfnOutput(scope, "SharedDbClusterArn", value=self.cluster_arn)
        if self.secret:
            CfnOutput(scope, "SharedDbSecretArn", value=self.secret.secret_arn)
