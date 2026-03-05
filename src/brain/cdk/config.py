"""CDK stack configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrainConfig:
    """Configuration for the Brain CDK stack."""

    cogent_name: str
    region: str = "us-east-1"
    db_min_acu: float = 0.5
    db_max_acu: float = 4.0
    executor_memory_mb: int = 2048
    executor_timeout_s: int = 900
    orchestrator_memory_mb: int = 512
    orchestrator_timeout_s: int = 60
    ecs_cpu: int = 2048
    ecs_memory: int = 4096
    ecs_timeout_s: int = 3600
