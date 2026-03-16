from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="module")
def web_gateway_env():
    env_vars = {
        "SKIP_JWT_VALIDATION": "1",
        "COGENT_NAME": "test",
        "DB_CLUSTER_ARN": "arn:aws:rds:us-east-1:000000000000:cluster:test",
        "DB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:test",
        "DB_NAME": "testdb",
        "EXECUTOR_FUNCTION_NAME": "test-executor",
    }
    old = {}
    for k, v in env_vars.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
