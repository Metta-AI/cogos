"""Tests for ECS dispatch path in ingress."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.db.models import ProcessStatus


class TestDispatchEcs:
    @patch("cogos.runtime.ingress.build_dispatch_event", return_value={"process_id": "test"})
    def test_ecs_runner_calls_run_task(self, _mock_build):
        from cogos.runtime.ingress import dispatch_single_process

        repo = MagicMock()
        proc = MagicMock()
        proc.id = uuid4()
        proc.runner = "ecs"
        proc.status = ProcessStatus.RUNNABLE

        dispatch_result = MagicMock()
        dispatch_result.run_id = str(uuid4())
        dispatch_result.delivery_id = None

        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123:task/abc"}]}

        dispatched = dispatch_single_process(
            repo=repo,
            process=proc,
            dispatch_result=dispatch_result,
            lambda_client=None,
            ecs_client=ecs_client,
            executor_function_name="test-executor",
            ecs_cluster="test-cluster",
            ecs_task_definition="test-taskdef",
        )
        assert dispatched
        ecs_client.run_task.assert_called_once()
