"""Lambda and ECS compute constructs."""

from __future__ import annotations

from aws_cdk import Duration, aws_ec2 as ec2, aws_ecs as ecs, aws_efs as efs, aws_iam as iam, aws_lambda as lambda_
from constructs import Construct

from brain.cdk.config import BrainConfig


class ComputeConstruct(Construct):
    """Lambda functions and ECS Fargate cluster/tasks."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
        vpc: ec2.IVpc,
        lambda_sg: ec2.ISecurityGroup,
        ecs_sg: ec2.ISecurityGroup,
        db_cluster_arn: str,
        db_secret_arn: str,
        filesystem: efs.IFileSystem,
        access_point: efs.IAccessPoint,
        event_bus_name: str,
    ) -> None:
        super().__init__(scope, id)

        safe_name = config.cogent_name.replace(".", "-")

        # Shared environment for Lambda functions
        env = {
            "COGENT_NAME": config.cogent_name,
            "COGENT_ID": config.cogent_name,
            "DB_CLUSTER_ARN": db_cluster_arn,
            "DB_SECRET_ARN": db_secret_arn,
            "DB_NAME": "cogent",
            "EVENT_BUS_NAME": event_bus_name,
            "AWS_REGION": config.region,
        }

        # Lambda execution role
        lambda_role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        # Allow Lambda to use Data API
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[db_cluster_arn],
            )
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[db_secret_arn],
            )
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse"],
                resources=["*"],
            )
        )

        # Orchestrator Lambda
        self.orchestrator = lambda_.Function(
            self,
            "Orchestrator",
            function_name=f"cogent-{safe_name}-orchestrator",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="brain.lambdas.orchestrator.handler.handler",
            code=lambda_.Code.from_asset("src"),
            memory_size=config.orchestrator_memory_mb,
            timeout=Duration.seconds(config.orchestrator_timeout_s),
            role=lambda_role,
            environment={
                **env,
                "EXECUTOR_FUNCTION_NAME": f"cogent-{safe_name}-executor",
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[lambda_sg],
        )

        # Executor Lambda
        self.executor = lambda_.Function(
            self,
            "Executor",
            function_name=f"cogent-{safe_name}-executor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="brain.lambdas.executor.handler.handler",
            code=lambda_.Code.from_asset("src"),
            memory_size=config.executor_memory_mb,
            timeout=Duration.seconds(config.executor_timeout_s),
            role=lambda_role,
            environment=env,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[lambda_sg],
            filesystem=lambda_.FileSystem.from_efs_access_point(
                access_point, "/mnt/cogent"
            ),
        )

        # Allow orchestrator to invoke executor
        self.executor.grant_invoke(self.orchestrator)

        # ECS Cluster
        self.cluster = ecs.Cluster(
            self,
            "Cluster",
            cluster_name=f"cogent-{safe_name}",
            vpc=vpc,
        )

        # ECS Task Role
        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[db_cluster_arn],
            )
        )
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[db_secret_arn],
            )
        )
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            )
        )

        # ECS Task Definition
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "ExecutorTask",
            family=f"cogent-{safe_name}-executor",
            cpu=config.ecs_cpu,
            memory_limit_mib=config.ecs_memory,
            task_role=task_role,
        )

        # Add EFS volume
        self.task_definition.add_volume(
            name="cogent-efs",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=filesystem.file_system_id,
                transit_encryption="ENABLED",
                authorization_config=ecs.AuthorizationConfig(
                    access_point_id=access_point.access_point_id,
                    iam="ENABLED",
                ),
            ),
        )

        container = self.task_definition.add_container(
            "Executor",
            image=ecs.ContainerImage.from_registry("python:3.12-slim"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="executor"),
            environment=env,
        )
        container.add_mount_points(
            ecs.MountPoint(
                container_path="/mnt/cogent",
                source_volume="cogent-efs",
                read_only=False,
            )
        )

        # Store for orchestrator to reference
        self.ecs_cluster_arn = self.cluster.cluster_arn
        self.ecs_task_definition_arn = self.task_definition.task_definition_arn
        self.ecs_subnets = ",".join(
            s.subnet_id for s in vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ).subnets
        )
        self.ecs_security_group_id = ecs_sg.security_group_id
