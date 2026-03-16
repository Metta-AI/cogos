"""CloudWatch monitoring constructs (alarms only)."""

from __future__ import annotations

from aws_cdk import Duration
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from cogtainer.cdk.config import CogtainerConfig


class MonitoringConstruct(Construct):
    """CloudWatch alarms and dashboards for cogtainer infrastructure."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: CogtainerConfig,
        orchestrator_fn: lambda_.IFunction,
        executor_fn: lambda_.IFunction,
        ingress_fn: lambda_.IFunction,
        ingress_queue: sqs.IQueue,
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

        cw.Alarm(
            self,
            "IngressErrors",
            alarm_name=f"cogent-{safe_name}-ingress-errors",
            metric=ingress_fn.metric_errors(period=Duration.minutes(5)),
            threshold=3,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        cw.Alarm(
            self,
            "IngressBacklog",
            alarm_name=f"cogent-{safe_name}-ingress-backlog",
            metric=ingress_queue.metric_approximate_number_of_messages_visible(period=Duration.minutes(5)),
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )
