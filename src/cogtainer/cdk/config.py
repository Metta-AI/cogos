"""CDK stack configuration."""

from __future__ import annotations

from dataclasses import dataclass

from aws_cdk import Duration

POLIS_ACCOUNT = "901289084804"
POLIS_REGION = "us-east-1"


@dataclass
class CogtainerConfig:
    """Configuration for the Cogtainer CDK stack."""

    cogent_name: str
    domain: str = "softmax-cogents.com"
    region: str = POLIS_REGION
    account: str = POLIS_ACCOUNT
    db_min_acu: float = 0.5
    db_max_acu: float = 4.0
    executor_memory_mb: int = 2048
    executor_timeout_s: int = 900
    orchestrator_memory_mb: int = 512
    orchestrator_timeout_s: int = 60
    ecs_cpu: int = 2048
    ecs_memory: int = 4096
    ecs_timeout_s: int = 3600
    ecr_repo_uri: str = ""
    llm_provider: str = "bedrock"
    session_expiry_days: Duration = Duration.days(30)
