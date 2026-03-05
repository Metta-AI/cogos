"""CloudWatch monitoring constructs."""

from __future__ import annotations

from aws_cdk import Duration, aws_cloudwatch as cw, aws_lambda as lambda_
from constructs import Construct

from brain.cdk.config import BrainConfig


class MonitoringConstruct(Construct):
    """CloudWatch alarms and dashboards for brain infrastructure."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
        orchestrator_fn: lambda_.IFunction,
        executor_fn: lambda_.IFunction,
    ) -> None:
        super().__init__(scope, id)

        safe_name = config.cogent_name.replace(".", "-")

        # Orchestrator error alarm
        cw.Alarm(
            self,
            "OrchestratorErrors",
            alarm_name=f"cogent-{safe_name}-orchestrator-errors",
            metric=orchestrator_fn.metric_errors(period=Duration.minutes(5)),
            threshold=5,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        # Executor error alarm
        cw.Alarm(
            self,
            "ExecutorErrors",
            alarm_name=f"cogent-{safe_name}-executor-errors",
            metric=executor_fn.metric_errors(period=Duration.minutes(5)),
            threshold=3,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        # Executor duration alarm (approaching timeout)
        cw.Alarm(
            self,
            "ExecutorDuration",
            alarm_name=f"cogent-{safe_name}-executor-duration",
            metric=executor_fn.metric_duration(period=Duration.minutes(5)),
            threshold=config.executor_timeout_s * 1000 * 0.9,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
