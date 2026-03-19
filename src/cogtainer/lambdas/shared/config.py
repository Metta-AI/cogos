"""Lambda configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LambdaConfig:
    cogent_name: str
    db_cluster_arn: str
    db_secret_arn: str
    db_name: str
    sessions_bucket: str
    event_bus_name: str
    region: str
    executor_function_name: str = ""
    ecs_cluster_arn: str = ""
    ecs_task_definition: str = ""
    ecs_subnets: str = ""
    ecs_security_group: str = ""
    sandbox_function_name: str = ""
    executor_image_override: str | None = None


_config: LambdaConfig | None = None


def get_config() -> LambdaConfig:
    """Return cached LambdaConfig singleton, loaded from env vars."""
    global _config
    if _config is None:
        _config = LambdaConfig(
            cogent_name=os.environ["COGENT_NAME"],
            db_cluster_arn=os.environ["DB_CLUSTER_ARN"],
            db_secret_arn=os.environ["DB_SECRET_ARN"],
            db_name=os.environ.get("DB_NAME", "cogent"),
            sessions_bucket=os.environ.get("SESSIONS_BUCKET", ""),
            event_bus_name=os.environ.get("EVENT_BUS_NAME", "default"),
            region=os.environ.get("AWS_REGION", "us-east-1"),
            executor_function_name=os.environ.get("EXECUTOR_FUNCTION_NAME", ""),
            ecs_cluster_arn=os.environ.get("ECS_CLUSTER_ARN", ""),
            ecs_task_definition=os.environ.get("ECS_TASK_DEFINITION", ""),
            ecs_subnets=os.environ.get("ECS_SUBNETS", ""),
            ecs_security_group=os.environ.get("ECS_SECURITY_GROUP", ""),
            sandbox_function_name=os.environ.get("SANDBOX_FUNCTION_NAME", ""),
            executor_image_override=os.environ.get("EXECUTOR_IMAGE_OVERRIDE"),
        )
    return _config
