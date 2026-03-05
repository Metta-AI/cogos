"""VPC and networking constructs."""

from __future__ import annotations

from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from brain.cdk.config import BrainConfig


class NetworkConstruct(Construct):
    """VPC with private and public subnets for brain infrastructure."""

    def __init__(self, scope: Construct, id: str, *, config: BrainConfig) -> None:
        super().__init__(scope, id)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name=f"cogent-{config.cogent_name}-brain",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        self.lambda_sg = ec2.SecurityGroup(
            self, "LambdaSg",
            vpc=self.vpc,
            description="Security group for Lambda functions",
            allow_all_outbound=True,
        )

        self.ecs_sg = ec2.SecurityGroup(
            self, "EcsSg",
            vpc=self.vpc,
            description="Security group for ECS tasks",
            allow_all_outbound=True,
        )

        self.db_sg = ec2.SecurityGroup(
            self, "DbSg",
            vpc=self.vpc,
            description="Security group for Aurora database",
        )

        # Allow Lambda and ECS to connect to Aurora
        self.db_sg.add_ingress_rule(
            self.lambda_sg,
            ec2.Port.tcp(5432),
            "Lambda to Aurora",
        )
        self.db_sg.add_ingress_rule(
            self.ecs_sg,
            ec2.Port.tcp(5432),
            "ECS to Aurora",
        )
