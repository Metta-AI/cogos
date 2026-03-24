"""Tests for RdsDataApiRepository._jsonb_safe and jsonb parameter handling."""
from __future__ import annotations

import enum
from datetime import datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from pydantic import BaseModel

from cogos.db.repository import RdsDataApiRepository


# ── _jsonb_safe ──────────────────────────────────────────────


class TestJsonbSafe:
    def test_none_passthrough(self):
        assert RdsDataApiRepository._jsonb_safe(None) is None

    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert RdsDataApiRepository._jsonb_safe(d) is d

    def test_list_passthrough(self):
        lst = [1, 2, 3]
        assert RdsDataApiRepository._jsonb_safe(lst) is lst

    def test_empty_dict(self):
        assert RdsDataApiRepository._jsonb_safe({}) == {}

    def test_empty_list(self):
        assert RdsDataApiRepository._jsonb_safe([]) == []

    def test_string_roundtrips(self):
        result = RdsDataApiRepository._jsonb_safe("hello")
        assert result == "hello"

    def test_int_roundtrips(self):
        result = RdsDataApiRepository._jsonb_safe(42)
        assert result == 42

    def test_enum_converted(self):
        class Color(enum.Enum):
            RED = "red"

        result = RdsDataApiRepository._jsonb_safe(Color.RED)
        assert isinstance(result, str)
        assert "RED" in result or "red" in result

    def test_pydantic_model_converted(self):
        class MyModel(BaseModel):
            name: str
            value: int

        result = RdsDataApiRepository._jsonb_safe(MyModel(name="test", value=42))
        # Should produce something JSON-safe (not crash)
        assert result is not None
        assert isinstance(result, (dict, str))

    def test_dict_with_uuid_values(self):
        """Dicts with UUID values pass through — json.dumps(default=str) in _param handles them."""
        d = {"id": uuid4(), "ts": datetime.now()}
        result = RdsDataApiRepository._jsonb_safe(d)
        assert result is d  # passthrough for dicts

    def test_nested_non_serializable(self):
        """Dicts with nested non-serializable objects pass through."""
        d = {"ids": [uuid4(), uuid4()]}
        result = RdsDataApiRepository._jsonb_safe(d)
        assert result is d


# ── _param jsonb behavior ────────────────────────────────────


class TestParamJsonb:
    def _make_repo(self):
        repo = RdsDataApiRepository.__new__(RdsDataApiRepository)
        return repo

    def test_dict_serialized_with_default_str(self):
        repo = self._make_repo()
        uid = UUID("12345678-1234-5678-1234-567812345678")
        param = repo._param("meta", {"id": uid})
        assert param["value"]["stringValue"] == '{"id": "12345678-1234-5678-1234-567812345678"}'

    def test_list_serialized(self):
        repo = self._make_repo()
        param = repo._param("items", [1, "two", 3])
        assert param["value"]["stringValue"] == '[1, "two", 3]'

    def test_none_is_null(self):
        repo = self._make_repo()
        param = repo._param("x", None)
        assert param["value"]["isNull"] is True

    def test_string_passthrough(self):
        repo = self._make_repo()
        param = repo._param("name", "hello")
        assert param["value"]["stringValue"] == "hello"


# ── Integration: _jsonb_safe applied before _execute ─────────


class TestJsonbSafeIntegration:
    def test_complete_run_sanitizes_result(self):
        """complete_run applies _jsonb_safe to result/snapshot/scope_log."""
        repo = RdsDataApiRepository.__new__(RdsDataApiRepository)
        repo._execute = MagicMock(return_value={"numberOfRecordsUpdated": 1})

        from cogos.db.models import RunStatus

        # Pass a result with UUID values — should not crash
        RdsDataApiRepository.complete_run(
            repo,
            uuid4(),
            status=RunStatus.COMPLETED,
            result={"process_id": uuid4()},
            scope_log=[{"action": "spawn", "target": uuid4()}],
        )

        assert repo._execute.called
        params = repo._execute.call_args.args[1]
        result_param = next(p for p in params if p["name"] == "result")
        # Should be valid JSON string (not crash)
        import json
        json.loads(result_param["value"]["stringValue"])

    def test_append_channel_message_sanitizes_payload(self):
        """append_channel_message applies _jsonb_safe to payload."""
        repo = RdsDataApiRepository.__new__(RdsDataApiRepository)
        repo._execute = MagicMock(
            return_value={
                "numberOfRecordsUpdated": 1,
                "columnMetadata": [
                    {"name": "id", "typeName": "uuid"},
                    {"name": "created_at", "typeName": "timestamptz"},
                ],
                "records": [
                    [
                        {"stringValue": str(uuid4())},
                        {"stringValue": "2026-01-01 00:00:00.000000"},
                    ]
                ],
            }
        )
        repo.match_handlers_by_channel = MagicMock(return_value=[])

        from cogos.db.models.channel_message import ChannelMessage

        msg = ChannelMessage(
            channel=uuid4(),
            sender_process=uuid4(),
            payload={"data": "test"},
        )
        # Should not crash
        repo.append_channel_message(msg)
        assert repo._execute.called
