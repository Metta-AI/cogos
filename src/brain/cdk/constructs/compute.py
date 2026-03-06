"""Lambda and ECS compute constructs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from aws_cdk import Duration
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

from brain.cdk.config import BrainConfig


def _build_lambda_package() -> str:
    """Build Lambda package with deps into a temp directory. Returns path."""
    build_dir = os.path.join(tempfile.gettempdir(), "cogent-lambda-build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    import sys

    # Install pydantic (boto3 is in Lambda runtime)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "pydantic", "-t", build_dir, "--quiet",
         "--platform", "manylinux2014_x86_64", "--only-binary=:all:",
         "--python-version", "3.12", "--implementation", "cp"],
    )
    # Copy src/ contents
    src_dir = "src"
    for item in os.listdir(src_dir):
        s = os.path.join(src_dir, item)
        d = os.path.join(build_dir, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    return build_dir


class ComputeConstruct(Construct):
    """Lambda functions and ECS task definition (uses shared polis cluster)."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
        db_cluster_arn: str,
        db_secret_arn: str,
        sessions_bucket: s3.IBucket,
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
            "SESSIONS_BUCKET": sessions_bucket.bucket_name,
        }

        # Shared policy statements for Data API access
        data_api_statements = [
            iam.PolicyStatement(
                actions=["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"],
                resources=[db_cluster_arn],
            ),
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[db_secret_arn],
            ),
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=["*"],
            ),
        ]

        lambda_basic = iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        )

        # Orchestrator role (no VPC needed — uses Data API)
        orchestrator_role = iam.Role(
            self,
            "OrchestratorRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[lambda_basic],
        )
        for stmt in data_api_statements:
            orchestrator_role.add_to_policy(stmt)
        orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:*:*:function:cogent-{safe_name}-executor"],
            )
        )
        orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask", "iam:PassRole"],
                resources=["*"],
            )
        )

        # Executor role (no VPC needed — uses Data API)
        executor_role = iam.Role(
            self,
            "ExecutorRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[lambda_basic],
        )
        for stmt in data_api_statements:
            executor_role.add_to_policy(stmt)
        executor_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse"],
                resources=["*"],
            )
        )

        # Lambda code with bundled dependencies
        lambda_code = lambda_.Code.from_asset(_build_lambda_package())

        # Orchestrator Lambda (no VPC — uses only AWS APIs)
        self.orchestrator = lambda_.Function(
            self,
            "Orchestrator",
            function_name=f"cogent-{safe_name}-orchestrator",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="brain.lambdas.orchestrator.handler.handler",
            code=lambda_code,
            memory_size=config.orchestrator_memory_mb,
            timeout=Duration.seconds(config.orchestrator_timeout_s),
            role=orchestrator_role,
            environment={
                **env,
                "EXECUTOR_FUNCTION_NAME": f"cogent-{safe_name}-executor",
            },
        )

        # Executor Lambda (no VPC — uses only AWS APIs)
        self.executor = lambda_.Function(
            self,
            "Executor",
            function_name=f"cogent-{safe_name}-executor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="brain.lambdas.executor.handler.handler",
            code=lambda_code,
            memory_size=config.executor_memory_mb,
            timeout=Duration.seconds(config.executor_timeout_s),
            role=executor_role,
            environment=env,
        )

        # ECS Task Role (for long-running tasks on shared cogent-polis cluster)
        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )
        for stmt in data_api_statements:
            task_role.add_to_policy(stmt)
        sessions_bucket.grant_read_write(task_role)

        # ECS Task Definition (runs on shared cogent-polis cluster)
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "ExecutorTask",
            family=f"cogent-{safe_name}-executor",
            cpu=config.ecs_cpu,
            memory_limit_mib=config.ecs_memory,
            task_role=task_role,
        )

        self.task_definition.add_container(
            "Executor",
            image=ecs.ContainerImage.from_registry("python:3.12-slim"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="executor"),
            environment=env,
        )
