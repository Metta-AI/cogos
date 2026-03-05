"""EventBridge event bus and rules."""

from __future__ import annotations

from aws_cdk import aws_events as events, aws_events_targets as targets, aws_lambda as lambda_
from constructs import Construct

from brain.cdk.config import BrainConfig


class EventBridgeConstruct(Construct):
    """Custom event bus with catch-all rule routing to orchestrator."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
        orchestrator_fn: lambda_.IFunction,
    ) -> None:
        super().__init__(scope, id)

        safe_name = config.cogent_name.replace(".", "-")

        self.event_bus = events.EventBus(
            self,
            "Bus",
            event_bus_name=f"cogent-{safe_name}",
        )

        # Route all events on this bus to the orchestrator
        events.Rule(
            self,
            "CatchAll",
            event_bus=self.event_bus,
            rule_name=f"cogent-{safe_name}-catch-all",
            event_pattern=events.EventPattern(
                source=events.Match.prefix(f"cogent."),
            ),
            targets=[targets.LambdaFunction(orchestrator_fn)],
        )

        self.bus_name = self.event_bus.event_bus_name
