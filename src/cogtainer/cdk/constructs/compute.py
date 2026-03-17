"""Lambda and ECS compute constructs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from cogtainer.cdk.config import CogtainerConfig


def _build_lambda_package() -> str:
    """Build Lambda package with deps into a temp directory. Returns path."""
    build_dir = os.path.join(tempfile.gettempdir(), "cogent-lambda-build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    # Install pydantic (boto3 is in Lambda runtime)
    # Use uv which is available in the project's toolchain
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv not found on PATH; needed to bundle Lambda dependencies")
    subprocess.check_call(
        [
            uv,
            "pip",
            "install",
            "pydantic",
            "anthropic",
            "--target",
            build_dir,
            "--quiet",
            "--python-platform",
            "linux",
            "--python-version",
            "3.12",
        ],
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
        config: CogtainerConfig,
        db_cluster_arn: str,
        db_secret_arn: str,
        sessions_bucket: s3.IBucket,
        event_bus_name: str,
    ) -> None:
        super().__init__(scope, id)

        safe_name = config.cogent_name.replace(".", "-")

        self.ingress_queue = sqs.Queue(
            self,
            "CogosIngressQueue",
            queue_name=f"cogent-{safe_name}-cogos-ingress.fifo",
            fifo=True,
            content_based_deduplication=False,
            visibility_timeout=Duration.seconds(60),
        )

        # Shared environment for Lambda functions
        env = {
            "COGENT_NAME": config.cogent_name,
            "COGENT_ID": config.cogent_name,
            "COGENT_DOMAIN": config.domain,
            "DB_CLUSTER_ARN": db_cluster_arn,
            "DB_RESOURCE_ARN": db_cluster_arn,
            "DB_SECRET_ARN": db_secret_arn,
            "DB_NAME": "cogent",
            "EVENT_BUS_NAME": event_bus_name,
            "SESSIONS_BUCKET": sessions_bucket.bucket_name,
            "COGOS_INGRESS_QUEUE_URL": self.ingress_queue.queue_url,
            "EXECUTOR_FUNCTION_NAME": f"cogent-{safe_name}-executor",
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

        lambda_basic = iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")

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
        executor_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:*:*:secret:cogent/{config.cogent_name}/*",
                    "arn:aws:secretsmanager:*:*:secret:cogent/polis/*",
                ],
            )
        )
        executor_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[
                    f"arn:aws:ses:*:*:identity/{config.domain}",
                    "arn:aws:ses:*:*:identity/*",
                ],
            )
        )
        sessions_bucket.grant_read_write(executor_role)

        # Lambda code with bundled dependencies
        lambda_code = lambda_.Code.from_asset(_build_lambda_package())

        # Orchestrator Lambda (no VPC — uses only AWS APIs)
        self.orchestrator = lambda_.Function(
            self,
            "Orchestrator",
            function_name=f"cogent-{safe_name}-orchestrator",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.orchestrator.handler.handler",
            code=lambda_code,
            memory_size=config.orchestrator_memory_mb,
            timeout=Duration.seconds(config.orchestrator_timeout_s),
            role=orchestrator_role,
            environment={
                **env,
                "EXECUTOR_FUNCTION_NAME": f"cogent-{safe_name}-executor",
            },
        )

        # Sandbox role — minimal permissions for Code Mode execution
        sandbox_role = iam.Role(
            self,
            "SandboxRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[lambda_basic],
        )
        for stmt in data_api_statements:
            sandbox_role.add_to_policy(stmt)
        sandbox_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::*:role/cogent-{safe_name}-tool-*"],
            )
        )

        # Sandbox Lambda — executes LLM-generated code in Code Mode
        self.sandbox = lambda_.Function(
            self,
            "Sandbox",
            function_name=f"cogent-{safe_name}-sandbox",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.sandbox.handler.handler",
            code=lambda_code,
            memory_size=256,
            timeout=Duration.seconds(30),
            role=sandbox_role,
            environment=env,
        )

        # Executor needs to invoke the sandbox
        executor_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[self.sandbox.function_arn],
            )
        )

        # Executor Lambda (no VPC — uses only AWS APIs)
        self.executor = lambda_.Function(
            self,
            "Executor",
            function_name=f"cogent-{safe_name}-executor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.executor.handler.handler",
            code=lambda_code,
            memory_size=config.executor_memory_mb,
            timeout=Duration.seconds(config.executor_timeout_s),
            role=executor_role,
            environment={
                **env,
                "SANDBOX_FUNCTION_NAME": f"cogent-{safe_name}-sandbox",
                "LLM_PROVIDER": config.llm_provider,
            },
        )
        self.ingress_queue.grant_send_messages(executor_role)

        # Dispatcher Lambda — runs CogOS scheduler tick
        dispatcher_role = iam.Role(
            self,
            "DispatcherRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[lambda_basic],
        )
        for stmt in data_api_statements:
            dispatcher_role.add_to_policy(stmt)
        dispatcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:*:*:function:cogent-{safe_name}-executor"],
            )
        )
        self.ingress_queue.grant_send_messages(dispatcher_role)

        self.dispatcher = lambda_.Function(
            self,
            "Dispatcher",
            function_name=f"cogent-{safe_name}-dispatcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.dispatcher.handler.handler",
            code=lambda_code,
            memory_size=256,
            timeout=Duration.seconds(65),
            role=dispatcher_role,
            environment=env,
        )

        ingress_role = iam.Role(
            self,
            "IngressRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[lambda_basic],
        )
        for stmt in data_api_statements:
            ingress_role.add_to_policy(stmt)
        ingress_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:*:*:function:cogent-{safe_name}-executor"],
            )
        )

        self.ingress = lambda_.Function(
            self,
            "Ingress",
            function_name=f"cogent-{safe_name}-ingress",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="cogtainer.lambdas.ingress.handler.handler",
            code=lambda_code,
            memory_size=256,
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=1,
            role=ingress_role,
            environment=env,
        )
        self.ingress.add_event_source(
            lambda_event_sources.SqsEventSource(
                self.ingress_queue,
                batch_size=10,
            )
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
        self.ingress_queue.grant_send_messages(task_role)
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )

        # Secrets Manager access for cogent and polis secrets
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:*:*:secret:cogent/{config.cogent_name}/*",
                    "arn:aws:secretsmanager:*:*:secret:cogent/polis/*",
                ],
            )
        )

        # SES email sending
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[f"arn:aws:ses:*:*:identity/{config.domain}"],
            )
        )

        # STS AssumeRole for Code Mode tool-specific IAM roles
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::*:role/cogent-{safe_name}-tool-*"],
            )
        )

        # SSM permissions for ECS Exec
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )

        # ECS Task Definition (runs on shared cogent-polis cluster)
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "ExecutorTask",
            family=f"cogent-{safe_name}-executor",
            cpu=config.ecs_cpu,
            memory_limit_mib=config.ecs_memory,
            task_role=task_role,
        )

        # Use custom executor image from polis ECR repo if available
        if config.ecr_repo_uri:
            image = ecs.ContainerImage.from_registry(f"{config.ecr_repo_uri}:executor-{safe_name}")
            # Grant execution role permission to pull from cross-account ECR
            self.task_definition.add_to_execution_role_policy(
                iam.PolicyStatement(
                    actions=["ecr:GetAuthorizationToken"],
                    resources=["*"],
                )
            )
            self.task_definition.add_to_execution_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                    ],
                    resources=["*"],
                )
            )
        else:
            image = ecs.ContainerImage.from_registry("python:3.12-slim")

        self.executor_task_log_group = logs.LogGroup(
            self,
            "ExecutorTaskExecutorLogGroup",
            log_group_name=f"/ecs/cogent-{safe_name}-executor",
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.task_definition.add_container(
            "Executor",
            image=image,
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="executor",
                log_group=self.executor_task_log_group,
            ),
            environment={
                **env,
                "CLAUDE_CODE_USE_BEDROCK": "1",
            },
        )

        # Look up default VPC for ECS task networking
        vpc = ec2.Vpc.from_lookup(self, "EcsVpc", is_default=True)
        ecs_sg = ec2.SecurityGroup(
            self,
            "EcsTaskSG",
            vpc=vpc,
            description=f"cogent-{safe_name} ECS executor tasks",
            allow_all_outbound=True,
        )
        public_subnets = vpc.select_subnets(subnet_type=ec2.SubnetType.PUBLIC)

        # Wire ECS config into orchestrator so it can launch tasks
        polis_cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "PolisCluster",
            cluster_name="cogent-polis",
            vpc=vpc,
            security_groups=[],
        )
        self.orchestrator.add_environment("ECS_CLUSTER_ARN", polis_cluster.cluster_arn)
        self.orchestrator.add_environment("ECS_TASK_DEFINITION", self.task_definition.task_definition_arn)
        self.orchestrator.add_environment("ECS_SUBNETS", ",".join(s.subnet_id for s in public_subnets.subnets))
        self.orchestrator.add_environment("ECS_SECURITY_GROUP", ecs_sg.security_group_id)
