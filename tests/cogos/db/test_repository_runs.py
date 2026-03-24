from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.db.models import RunStatus
from cogos.db.repository import RdsDataApiRepository


def test_complete_run_updates_snapshot_when_provided():
    repo = RdsDataApiRepository.__new__(RdsDataApiRepository)
    repo._execute = MagicMock(return_value={"numberOfRecordsUpdated": 1})

    result = RdsDataApiRepository.complete_run(
        repo,
        uuid4(),
        status=RunStatus.COMPLETED,
        snapshot={"final_key": "/proc/x/final.json"},
    )

    assert result is True

    sql = repo._execute.call_args.args[0]
    params = repo._execute.call_args.args[1]

    assert "snapshot = COALESCE(:snapshot::jsonb, snapshot)" in sql
    snapshot_param = next(param for param in params if param["name"] == "snapshot")
    assert snapshot_param["value"]["stringValue"] == '{"final_key": "/proc/x/final.json"}'
