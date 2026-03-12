# Channels Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace free-form text events with explicit typed channels — schemas, channel model, process handles, and named topic channels.

**Architecture:** Bottom-up — data models first, then capabilities, then rewire ingress/executor/bridges, then dashboard. Each task is independently testable. Clean cut: drop old event tables, no dual-write.

**Tech Stack:** Python, Pydantic, PostgreSQL (RDS Data API), FastAPI (dashboard), LocalRepository (test/dev)

**Design doc:** `docs/cogos/channels.md`

---

### Task 1: Schema Data Models

**Files:**
- Create: `src/cogos/db/models/schema.py`
- Create: `src/cogos/db/models/channel.py`
- Create: `src/cogos/db/models/channel_message.py`
- Modify: `src/cogos/db/models/__init__.py`
- Test: `tests/cogos/db/test_channel_models.py`

**Step 1: Write the failing test**

```python
"""Tests for channel and schema data models."""
from uuid import uuid4

from cogos.db.models import Channel, ChannelMessage, ChannelType, Schema


def test_schema_defaults():
    s = Schema(name="metrics", definition={"fields": {"value": "number"}})
    assert s.name == "metrics"
    assert s.id is not None
    assert s.file_id is None


def test_channel_defaults():
    pid = uuid4()
    ch = Channel(name="process:worker", owner_process=pid, channel_type=ChannelType.IMPLICIT)
    assert ch.channel_type == ChannelType.IMPLICIT
    assert ch.auto_close is False
    assert ch.closed_at is None


def test_channel_message_defaults():
    cid = uuid4()
    pid = uuid4()
    msg = ChannelMessage(channel=cid, sender_process=pid, payload={"body": "hi"})
    assert msg.payload == {"body": "hi"}
    assert msg.id is not None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/db/test_channel_models.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

`src/cogos/db/models/schema.py`:
```python
"""Schema model — declarative message type definitions."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Schema(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    definition: dict[str, Any] = Field(default_factory=dict)
    file_id: UUID | None = None  # FK -> File.id
    created_at: datetime | None = None
```

`src/cogos/db/models/channel.py`:
```python
"""Channel model — typed append-only message stream."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChannelType(str, enum.Enum):
    IMPLICIT = "implicit"
    SPAWN = "spawn"
    NAMED = "named"


class Channel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    owner_process: UUID  # FK -> Process.id
    schema_id: UUID | None = None  # FK -> Schema.id
    inline_schema: dict[str, Any] | None = None
    channel_type: ChannelType
    auto_close: bool = False
    closed_at: datetime | None = None
    created_at: datetime | None = None
```

`src/cogos/db/models/channel_message.py`:
```python
"""ChannelMessage model — individual message in a channel."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChannelMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel: UUID  # FK -> Channel.id
    sender_process: UUID  # FK -> Process.id
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
```

Add to `src/cogos/db/models/__init__.py`:
```python
from cogos.db.models.channel import Channel, ChannelType
from cogos.db.models.channel_message import ChannelMessage
from cogos.db.models.schema import Schema
```

And add `"Channel"`, `"ChannelType"`, `"ChannelMessage"`, `"Schema"` to `__all__`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/db/test_channel_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/db/models/schema.py src/cogos/db/models/channel.py src/cogos/db/models/channel_message.py src/cogos/db/models/__init__.py tests/cogos/db/test_channel_models.py
git commit -m "feat(channels): add Schema, Channel, ChannelMessage data models"
```

---

### Task 2: Schema Validation Engine

**Files:**
- Create: `src/cogos/channels/schema_validator.py`
- Test: `tests/cogos/channels/test_schema_validator.py`

**Step 1: Write the failing test**

```python
"""Tests for schema validation — type checking, nested schemas, inline schemas."""
import pytest

from cogos.channels.schema_validator import SchemaValidator, SchemaValidationError


class TestBasicTypes:
    def test_string_valid(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        v.validate({"name": "hello"})

    def test_string_invalid(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"name": 123})

    def test_number_valid(self):
        v = SchemaValidator({"fields": {"value": "number"}})
        v.validate({"value": 42})
        v.validate({"value": 3.14})

    def test_bool_valid(self):
        v = SchemaValidator({"fields": {"flag": "bool"}})
        v.validate({"flag": True})

    def test_list_valid(self):
        v = SchemaValidator({"fields": {"items": "list"}})
        v.validate({"items": [1, 2, 3]})

    def test_typed_list_valid(self):
        v = SchemaValidator({"fields": {"tags": "list[string]"}})
        v.validate({"tags": ["a", "b"]})

    def test_typed_list_invalid_element(self):
        v = SchemaValidator({"fields": {"tags": "list[string]"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"tags": ["a", 123]})

    def test_dict_valid(self):
        v = SchemaValidator({"fields": {"meta": "dict"}})
        v.validate({"meta": {"k": "v"}})

    def test_missing_required_field(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        with pytest.raises(SchemaValidationError):
            v.validate({})

    def test_extra_field_rejected(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"name": "hi", "extra": True})


class TestNestedSchemas:
    def test_inline_sub_schema(self):
        v = SchemaValidator({"fields": {"pos": {"x": "number", "y": "number"}}})
        v.validate({"pos": {"x": 1.0, "y": 2.0}})

    def test_inline_sub_schema_invalid(self):
        v = SchemaValidator({"fields": {"pos": {"x": "number", "y": "number"}}})
        with pytest.raises(SchemaValidationError):
            v.validate({"pos": {"x": "bad"}})

    def test_named_sub_schema(self):
        registry = {
            "position": {"fields": {"x": "number", "y": "number"}},
        }
        v = SchemaValidator(
            {"fields": {"pos": "position"}},
            schema_registry=registry,
        )
        v.validate({"pos": {"x": 1.0, "y": 2.0}})

    def test_list_of_sub_schema(self):
        registry = {
            "position": {"fields": {"x": "number", "y": "number"}},
        }
        v = SchemaValidator(
            {"fields": {"targets": "list[position]"}},
            schema_registry=registry,
        )
        v.validate({"targets": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/channels/test_schema_validator.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

`src/cogos/channels/__init__.py`: empty file

`src/cogos/channels/schema_validator.py`:
```python
"""Schema validation engine for channel messages."""
from __future__ import annotations

from typing import Any


class SchemaValidationError(Exception):
    pass


# Map type names to Python type checks
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
}


class SchemaValidator:
    """Validate payloads against a schema definition.

    Schema format: {"fields": {"name": "type", ...}}
    Types: string, number, bool, list, list[T], dict, dict[K,V],
           or a reference to another schema name in the registry.
    Sub-schemas can be inline dicts: {"x": "number", "y": "number"}.
    """

    def __init__(
        self,
        definition: dict[str, Any],
        *,
        schema_registry: dict[str, dict] | None = None,
    ) -> None:
        self._fields: dict[str, Any] = definition.get("fields", {})
        self._registry = schema_registry or {}

    def validate(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise SchemaValidationError(f"Expected dict, got {type(payload).__name__}")
        self._validate_fields(self._fields, payload, path="")

    def _validate_fields(
        self, fields: dict[str, Any], data: dict[str, Any], path: str
    ) -> None:
        # Check for missing fields
        for name in fields:
            if name not in data:
                loc = f"{path}.{name}" if path else name
                raise SchemaValidationError(f"Missing required field: {loc}")

        # Check for extra fields
        for name in data:
            if name not in fields:
                loc = f"{path}.{name}" if path else name
                raise SchemaValidationError(f"Unexpected field: {loc}")

        # Validate each field
        for name, type_spec in fields.items():
            loc = f"{path}.{name}" if path else name
            self._validate_value(type_spec, data[name], loc)

    def _validate_value(self, type_spec: Any, value: Any, path: str) -> None:
        # Inline sub-schema (dict of field defs)
        if isinstance(type_spec, dict):
            if not isinstance(value, dict):
                raise SchemaValidationError(
                    f"{path}: expected object, got {type(value).__name__}"
                )
            self._validate_fields(type_spec, value, path)
            return

        if not isinstance(type_spec, str):
            raise SchemaValidationError(f"{path}: invalid type spec: {type_spec!r}")

        # Parameterized type: list[T]
        if type_spec.startswith("list[") and type_spec.endswith("]"):
            if not isinstance(value, list):
                raise SchemaValidationError(
                    f"{path}: expected list, got {type(value).__name__}"
                )
            inner = type_spec[5:-1]
            for i, item in enumerate(value):
                self._validate_value(inner, item, f"{path}[{i}]")
            return

        # Basic types
        if type_spec in _TYPE_MAP:
            expected = _TYPE_MAP[type_spec]
            # bool is subclass of int in Python — reject int when expecting bool
            if type_spec == "bool" and isinstance(value, int) and not isinstance(value, bool):
                raise SchemaValidationError(
                    f"{path}: expected bool, got int"
                )
            if type_spec == "number" and isinstance(value, bool):
                raise SchemaValidationError(
                    f"{path}: expected number, got bool"
                )
            if not isinstance(value, expected):
                raise SchemaValidationError(
                    f"{path}: expected {type_spec}, got {type(value).__name__}"
                )
            return

        # Schema reference (look up in registry)
        if type_spec in self._registry:
            if not isinstance(value, dict):
                raise SchemaValidationError(
                    f"{path}: expected {type_spec} object, got {type(value).__name__}"
                )
            ref_fields = self._registry[type_spec].get("fields", {})
            self._validate_fields(ref_fields, value, path)
            return

        raise SchemaValidationError(f"{path}: unknown type '{type_spec}'")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/channels/test_schema_validator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/channels/__init__.py src/cogos/channels/schema_validator.py tests/cogos/channels/__init__.py tests/cogos/channels/test_schema_validator.py
git commit -m "feat(channels): add schema validation engine with nested/referenced schemas"
```

---

### Task 3: SQL Migration — New Tables, Drop Old Tables

**Files:**
- Create: `src/cogos/db/migrations/006_channels.sql`
- Test: `tests/cogos/test_cli_migrations.py` (extend existing)

**Step 1: Write the migration SQL**

`src/cogos/db/migrations/006_channels.sql`:
```sql
-- Channels migration: add schema, channel, channel_message tables;
-- drop event, event_delivery, event_outbox, event_type tables;
-- modify handler to use channel FK instead of event_pattern.

-- ═══════════════════════════════════════════════════════════
-- NEW TABLES
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cogos_schema (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    definition  JSONB NOT NULL DEFAULT '{}',
    file_id     UUID REFERENCES cogos_file(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cogos_channel (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    owner_process   UUID REFERENCES cogos_process(id),
    schema_id       UUID REFERENCES cogos_schema(id),
    inline_schema   JSONB,
    channel_type    TEXT NOT NULL DEFAULT 'named'
                    CHECK (channel_type IN ('implicit', 'spawn', 'named')),
    auto_close      BOOLEAN NOT NULL DEFAULT FALSE,
    closed_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cogos_channel_owner ON cogos_channel(owner_process);
CREATE INDEX IF NOT EXISTS idx_cogos_channel_type ON cogos_channel(channel_type);

CREATE TABLE IF NOT EXISTS cogos_channel_message (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel         UUID NOT NULL REFERENCES cogos_channel(id) ON DELETE CASCADE,
    sender_process  UUID REFERENCES cogos_process(id),
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cogos_channel_message_channel ON cogos_channel_message(channel, created_at);

-- ═══════════════════════════════════════════════════════════
-- MODIFY HANDLER: add channel FK, drop event_pattern
-- ═══════════════════════════════════════════════════════════

ALTER TABLE cogos_handler ADD COLUMN IF NOT EXISTS channel UUID REFERENCES cogos_channel(id);
ALTER TABLE cogos_handler DROP CONSTRAINT IF EXISTS cogos_handler_process_event_pattern_key;
ALTER TABLE cogos_handler DROP COLUMN IF EXISTS event_pattern;

-- ═══════════════════════════════════════════════════════════
-- MODIFY PROCESS: add schema_id, drop output_events
-- ═══════════════════════════════════════════════════════════

ALTER TABLE cogos_process ADD COLUMN IF NOT EXISTS schema_id UUID REFERENCES cogos_schema(id);
ALTER TABLE cogos_process DROP COLUMN IF EXISTS output_events;

-- ═══════════════════════════════════════════════════════════
-- DROP OLD EVENT TABLES
-- ═══════════════════════════════════════════════════════════

DROP TABLE IF EXISTS cogos_event_outbox CASCADE;
DROP TABLE IF EXISTS cogos_event_delivery CASCADE;
DROP TABLE IF EXISTS cogos_event_type CASCADE;
DROP TABLE IF EXISTS cogos_event CASCADE;
```

**Step 2: Verify migration applies cleanly**

Run: `python -m pytest tests/cogos/test_cli_migrations.py -v`
Expected: PASS (existing migration tests should still pass; the new SQL file is picked up by `apply_cogos_sql_migrations`)

**Step 3: Commit**

```bash
git add src/cogos/db/migrations/006_channels.sql
git commit -m "feat(channels): SQL migration — new channel/schema tables, drop event tables"
```

---

### Task 4: LocalRepository — Channel and Schema CRUD

**Files:**
- Modify: `src/cogos/db/local_repository.py`
- Test: `tests/cogos/db/test_local_repo_channels.py`

**Step 1: Write the failing test**

```python
"""Tests for LocalRepository channel and schema CRUD."""
from uuid import uuid4

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Schema,
)


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(str(tmp_path))


@pytest.fixture
def process(repo):
    p = Process(name="test-proc", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    return p


class TestSchemaCRUD:
    def test_upsert_and_get(self, repo):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        sid = repo.upsert_schema(s)
        assert sid == s.id
        got = repo.get_schema(sid)
        assert got.name == "metrics"

    def test_get_by_name(self, repo):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        repo.upsert_schema(s)
        got = repo.get_schema_by_name("metrics")
        assert got is not None
        assert got.id == s.id

    def test_list_schemas(self, repo):
        repo.upsert_schema(Schema(name="a", definition={}))
        repo.upsert_schema(Schema(name="b", definition={}))
        assert len(repo.list_schemas()) == 2


class TestChannelCRUD:
    def test_create_and_get(self, repo, process):
        ch = Channel(name="process:test-proc", owner_process=process.id, channel_type=ChannelType.IMPLICIT)
        cid = repo.upsert_channel(ch)
        got = repo.get_channel(cid)
        assert got.name == "process:test-proc"

    def test_get_by_name(self, repo, process):
        ch = Channel(name="my-channel", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        got = repo.get_channel_by_name("my-channel")
        assert got is not None

    def test_list_channels(self, repo, process):
        repo.upsert_channel(Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED))
        repo.upsert_channel(Channel(name="ch2", owner_process=process.id, channel_type=ChannelType.NAMED))
        assert len(repo.list_channels()) == 2

    def test_list_channels_by_owner(self, repo, process):
        p2 = Process(name="other", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
        repo.upsert_process(p2)
        repo.upsert_channel(Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED))
        repo.upsert_channel(Channel(name="ch2", owner_process=p2.id, channel_type=ChannelType.NAMED))
        assert len(repo.list_channels(owner_process=process.id)) == 1

    def test_close_channel(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        repo.close_channel(ch.id)
        got = repo.get_channel(ch.id)
        assert got.closed_at is not None


class TestChannelMessageCRUD:
    def test_append_and_list(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        msg = ChannelMessage(channel=ch.id, sender_process=process.id, payload={"body": "hello"})
        mid = repo.append_channel_message(msg)
        assert mid == msg.id
        msgs = repo.list_channel_messages(ch.id)
        assert len(msgs) == 1
        assert msgs[0].payload == {"body": "hello"}

    def test_list_with_limit(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        for i in range(5):
            repo.append_channel_message(
                ChannelMessage(channel=ch.id, sender_process=process.id, payload={"i": i})
            )
        assert len(repo.list_channel_messages(ch.id, limit=3)) == 3


class TestHandlerWithChannel:
    def test_handler_binds_to_channel(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        h = Handler(process=process.id, channel=ch.id)
        hid = repo.create_handler(h)
        handlers = repo.match_handlers_by_channel(ch.id)
        assert len(handlers) == 1
        assert handlers[0].id == hid
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/db/test_local_repo_channels.py -v`
Expected: FAIL

**Step 3: Implement LocalRepository methods**

Add to `src/cogos/db/local_repository.py`:
- `_schemas: dict[UUID, Schema]` storage
- `_channels: dict[UUID, Channel]` storage
- `_channel_messages: dict[UUID, ChannelMessage]` storage
- `upsert_schema(s: Schema) -> UUID`
- `get_schema(sid: UUID) -> Schema | None`
- `get_schema_by_name(name: str) -> Schema | None`
- `list_schemas() -> list[Schema]`
- `upsert_channel(ch: Channel) -> UUID`
- `get_channel(cid: UUID) -> Channel | None`
- `get_channel_by_name(name: str) -> Channel | None`
- `list_channels(*, owner_process: UUID | None = None) -> list[Channel]`
- `close_channel(cid: UUID) -> bool`
- `append_channel_message(msg: ChannelMessage) -> UUID`
- `list_channel_messages(channel_id: UUID, *, limit: int = 100) -> list[ChannelMessage]`
- `match_handlers_by_channel(channel_id: UUID) -> list[Handler]`

Also update `Handler` model to add optional `channel` field:
```python
# In src/cogos/db/models/handler.py
class Handler(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    process: UUID
    event_pattern: str | None = None  # deprecated, will be removed
    channel: UUID | None = None  # FK -> Channel.id
    enabled: bool = True
    created_at: datetime | None = None
```

And update `Process` model:
```python
# In src/cogos/db/models/process.py — add field
schema_id: UUID | None = None  # FK -> Schema.id
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/db/test_local_repo_channels.py -v`
Expected: PASS

**Step 5: Run all existing tests to check nothing broke**

Run: `python -m pytest tests/cogos/ -v`
Expected: PASS (handler tests may need `event_pattern` default updates)

**Step 6: Commit**

```bash
git add src/cogos/db/local_repository.py src/cogos/db/models/handler.py src/cogos/db/models/process.py tests/cogos/db/test_local_repo_channels.py
git commit -m "feat(channels): LocalRepository CRUD for schemas, channels, messages"
```

---

### Task 5: Repository (RDS) — Channel and Schema CRUD

**Files:**
- Modify: `src/cogos/db/repository.py`
- Test: (uses same patterns as LocalRepository — integration test skipped for now, relies on LocalRepository tests as proxy)

**Step 1: Add methods to Repository**

Mirror all methods from Task 4 but using SQL via RDS Data API:
- `upsert_schema`, `get_schema`, `get_schema_by_name`, `list_schemas`
- `upsert_channel`, `get_channel`, `get_channel_by_name`, `list_channels`, `close_channel`
- `append_channel_message`, `list_channel_messages`
- `match_handlers_by_channel`

Follow the same patterns as existing `append_event`, `get_events`, etc. — parameterized SQL via `self.query()` and `self.execute()`.

**Step 2: Run existing tests**

Run: `python -m pytest tests/cogos/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/cogos/db/repository.py
git commit -m "feat(channels): Repository (RDS) CRUD for schemas, channels, messages"
```

---

### Task 6: Schemas Capability

**Files:**
- Create: `src/cogos/capabilities/schemas.py`
- Test: `tests/cogos/capabilities/test_schemas_capability.py`

**Step 1: Write the failing test**

```python
"""Tests for SchemasCapability."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.schemas import SchemasCapability
from cogos.db.models import Schema


@pytest.fixture
def repo():
    mock = MagicMock()
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestSchemaGet:
    def test_get_existing(self, repo, pid):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        repo.get_schema_by_name.return_value = s
        cap = SchemasCapability(repo, pid)
        result = cap.get("metrics")
        assert result.name == "metrics"
        assert result.definition == {"fields": {"value": "number"}}

    def test_get_missing(self, repo, pid):
        repo.get_schema_by_name.return_value = None
        cap = SchemasCapability(repo, pid)
        result = cap.get("nonexistent")
        assert hasattr(result, "error")


class TestSchemaList:
    def test_list(self, repo, pid):
        repo.list_schemas.return_value = [
            Schema(name="a", definition={}),
            Schema(name="b", definition={}),
        ]
        cap = SchemasCapability(repo, pid)
        result = cap.list()
        assert len(result) == 2


class TestSchemaScoping:
    def test_scoped_allows_matching(self, repo, pid):
        s = Schema(name="metrics", definition={})
        repo.get_schema_by_name.return_value = s
        cap = SchemasCapability(repo, pid).scope(names=["metrics*"])
        cap.get("metrics")  # should not raise

    def test_scoped_denies_non_matching(self, repo, pid):
        cap = SchemasCapability(repo, pid).scope(names=["metrics*"])
        with pytest.raises(PermissionError):
            cap.get("secrets")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/capabilities/test_schemas_capability.py -v`
Expected: FAIL with ImportError

**Step 3: Write implementation**

`src/cogos/capabilities/schemas.py`:
```python
"""Schemas capability — load and list schema definitions."""
from __future__ import annotations

import fnmatch
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability


class SchemaInfo(BaseModel):
    name: str
    definition: dict[str, Any]
    file_id: str | None = None


class SchemaError(BaseModel):
    error: str


class SchemasCapability(Capability):
    """Schema definitions for channel messages.

    Usage:
        schemas.get("metrics")
        schemas.list()
    """

    def _narrow(self, existing: dict, requested: dict) -> dict:
        old = existing.get("names")
        new = requested.get("names")
        if old is not None and new is not None:
            if "*" in old:
                return {"names": new}
            if "*" in new:
                return {"names": old}
            return {"names": [p for p in old if p in new]}
        return {"names": old or new or ["*"]}

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        patterns = self._scope.get("names")
        if patterns is None:
            return
        name = context.get("name", "")
        if not name:
            return
        for pattern in patterns:
            if fnmatch.fnmatch(str(name), pattern):
                return
        raise PermissionError(
            f"Schema '{name}' not permitted; allowed patterns: {patterns}"
        )

    def get(self, name: str) -> SchemaInfo | SchemaError:
        self._check("get", name=name)
        s = self.repo.get_schema_by_name(name)
        if s is None:
            return SchemaError(error=f"Schema '{name}' not found")
        return SchemaInfo(
            name=s.name,
            definition=s.definition,
            file_id=str(s.file_id) if s.file_id else None,
        )

    def list(self) -> list[SchemaInfo]:
        schemas = self.repo.list_schemas()
        return [
            SchemaInfo(name=s.name, definition=s.definition,
                       file_id=str(s.file_id) if s.file_id else None)
            for s in schemas
        ]

    def __repr__(self) -> str:
        return "<SchemasCapability get() list()>"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/capabilities/test_schemas_capability.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/schemas.py tests/cogos/capabilities/test_schemas_capability.py
git commit -m "feat(channels): add SchemasCapability"
```

---

### Task 7: Channels Capability

**Files:**
- Create: `src/cogos/capabilities/channels.py`
- Test: `tests/cogos/capabilities/test_channels_capability.py`

**Step 1: Write the failing test**

```python
"""Tests for ChannelsCapability — create, list, get, send, read, subscribe, close."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.channels import ChannelsCapability
from cogos.db.models import Channel, ChannelMessage, ChannelType, Handler, Schema


@pytest.fixture
def repo():
    mock = MagicMock()
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestCreate:
    def test_create_with_inline_schema(self, repo, pid):
        repo.upsert_channel.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.create("metrics", schema={"value": "number"})
        assert result.name == "metrics"
        repo.upsert_channel.assert_called_once()

    def test_create_with_named_schema(self, repo, pid):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        repo.get_schema_by_name.return_value = s
        repo.upsert_channel.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.create("metrics", schema="metrics")
        assert result.name == "metrics"

    def test_create_missing_schema_ref(self, repo, pid):
        repo.get_schema_by_name.return_value = None
        cap = ChannelsCapability(repo, pid)
        result = cap.create("metrics", schema="nonexistent")
        assert hasattr(result, "error")


class TestSendAndRead:
    def test_send_valid(self, repo, pid):
        ch = Channel(name="ch1", owner_process=pid, channel_type=ChannelType.NAMED,
                     inline_schema={"fields": {"body": "string"}})
        repo.get_channel.return_value = ch
        repo.get_channel_by_name.return_value = ch
        repo.append_channel_message.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.send("ch1", {"body": "hello"})
        assert hasattr(result, "id")

    def test_read(self, repo, pid):
        ch = Channel(name="ch1", owner_process=pid, channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=ch.id, sender_process=pid, payload={"body": "hi"}),
        ]
        cap = ChannelsCapability(repo, pid)
        result = cap.read("ch1")
        assert len(result) == 1


class TestSubscribe:
    def test_subscribe_creates_handler(self, repo, pid):
        ch = Channel(name="ch1", owner_process=uuid4(), channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        repo.create_handler.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.subscribe("ch1")
        repo.create_handler.assert_called_once()


class TestScoping:
    def test_scoped_create_allowed(self, repo, pid):
        repo.upsert_channel.return_value = uuid4()
        cap = ChannelsCapability(repo, pid).scope(ops=["create", "list", "get"])
        cap.create("metrics", schema={"value": "number"})

    def test_scoped_create_denied(self, repo, pid):
        cap = ChannelsCapability(repo, pid).scope(ops=["list", "get"])
        with pytest.raises(PermissionError):
            cap.create("metrics", schema={"value": "number"})
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/capabilities/test_channels_capability.py -v`
Expected: FAIL

**Step 3: Write implementation**

`src/cogos/capabilities/channels.py` — implements create, list, get, send, read, subscribe, close, schema with scoping on ops and name patterns. Uses `SchemaValidator` for message validation on send.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/capabilities/test_channels_capability.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/channels.py tests/cogos/capabilities/test_channels_capability.py
git commit -m "feat(channels): add ChannelsCapability with send/read/subscribe/close"
```

---

### Task 8: Process Handle

**Files:**
- Create: `src/cogos/capabilities/process_handle.py`
- Modify: `src/cogos/capabilities/procs.py`
- Test: `tests/cogos/capabilities/test_process_handle.py`

**Step 1: Write the failing test**

```python
"""Tests for ProcessHandle — send, recv, kill, status, wait."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.process_handle import ProcessHandle
from cogos.db.models import Channel, ChannelMessage, ChannelType, Process, ProcessMode, ProcessStatus


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def parent_id():
    return uuid4()


@pytest.fixture
def child_process():
    return Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)


class TestSendRecv:
    def test_send(self, repo, parent_id, child_process):
        send_ch = Channel(name=f"spawn:{parent_id}→{child_process.id}",
                          owner_process=parent_id, channel_type=ChannelType.SPAWN)
        recv_ch = Channel(name=f"spawn:{child_process.id}→{parent_id}",
                          owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.append_channel_message.return_value = uuid4()

        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=send_ch, recv_channel=recv_ch,
        )
        result = handle.send({"body": "task"})
        repo.append_channel_message.assert_called_once()

    def test_recv(self, repo, parent_id, child_process):
        send_ch = Channel(name="s", owner_process=parent_id, channel_type=ChannelType.SPAWN)
        recv_ch = Channel(name="r", owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=recv_ch.id, sender_process=child_process.id, payload={"result": "done"}),
        ]
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=send_ch, recv_channel=recv_ch,
        )
        msgs = handle.recv()
        assert len(msgs) == 1


class TestKillAndStatus:
    def test_kill(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        repo.get_process.return_value = child_process
        handle.kill()
        repo.update_process_status.assert_called_once_with(child_process.id, ProcessStatus.DISABLED)

    def test_status(self, repo, parent_id, child_process):
        repo.get_process.return_value = child_process
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        assert handle.status() == "runnable"


class TestWait:
    def test_wait_returns_wait_spec(self, repo, parent_id, child_process):
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        spec = handle.wait()
        assert spec["type"] == "wait"
        assert spec["process_ids"] == [str(child_process.id)]

    def test_wait_any(self, repo, parent_id):
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1, send_channel=None, recv_channel=None)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2, send_channel=None, recv_channel=None)
        spec = ProcessHandle.wait_any([h1, h2])
        assert spec["type"] == "wait_any"
        assert len(spec["process_ids"]) == 2

    def test_wait_all(self, repo, parent_id):
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1, send_channel=None, recv_channel=None)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2, send_channel=None, recv_channel=None)
        spec = ProcessHandle.wait_all([h1, h2])
        assert spec["type"] == "wait_all"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/capabilities/test_process_handle.py -v`
Expected: FAIL

**Step 3: Write implementation**

`src/cogos/capabilities/process_handle.py`:
- `ProcessHandle` class with `send()`, `recv()`, `kill()`, `status()`, `wait()`, `channel` property, `schema()` method
- Static methods `wait_any()`, `wait_all()` that return wait spec dicts
- Wait specs are dicts `{"type": "wait"|"wait_any"|"wait_all", "process_ids": [...]}` — the executor will interpret these to end the run and create handler subscriptions

Then update `src/cogos/capabilities/procs.py`:
- `spawn()` returns a `ProcessHandle` instead of `SpawnResult`
- `get()` returns a `ProcessHandle` instead of `ProcessDetail`
- Both create spawn channels when spawning, look up existing channels when getting

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/capabilities/test_process_handle.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/process_handle.py src/cogos/capabilities/procs.py tests/cogos/capabilities/test_process_handle.py
git commit -m "feat(channels): add ProcessHandle with send/recv/kill/wait"
```

---

### Task 9: Update Scheduler — Channel-Based Delivery

**Files:**
- Modify: `src/cogos/capabilities/scheduler.py`
- Modify: `src/cogos/runtime/ingress.py`
- Test: `tests/cogos/test_scheduler_channels.py`

**Step 1: Write the failing test**

```python
"""Tests for channel-based scheduler delivery."""
from uuid import UUID, uuid4

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def test_message_wakes_subscribed_process(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(name="worker", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(proc)

    ch = Channel(name="io:discord:general", owner_process=uuid4(), channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    # Write a message to the channel
    msg = ChannelMessage(channel=ch.id, sender_process=uuid4(), payload={"content": "hello"})
    repo.append_channel_message(msg)

    # Scheduler should detect new messages and wake the process
    result = scheduler.match_channel_messages()
    assert result.deliveries_created >= 1
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE
```

**Step 2: Implement**

Update `SchedulerCapability`:
- Add `match_channel_messages()` that scans for new channel messages, matches them to handlers bound to those channels, creates deliveries, and wakes processes.
- Keep `deliver_event()` signature but adapt internals to work with channel messages.

Update `ingress.py`:
- `drain_outbox` → `drain_channel_messages` (or keep outbox pattern but keyed on channel messages)

**Step 3: Run tests**

Run: `python -m pytest tests/cogos/test_scheduler_channels.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/capabilities/scheduler.py src/cogos/runtime/ingress.py tests/cogos/test_scheduler_channels.py
git commit -m "feat(channels): scheduler delivers channel messages to handlers"
```

---

### Task 10: Update Executor — Channel Message Context

**Files:**
- Modify: `src/cogos/executor/handler.py`
- Test: `tests/cogos/test_executor_channels.py`

**Step 1: Update executor**

In `execute_process()`:
- Instead of passing `event_data` dict with `event_type`/`payload`, pass channel message data
- Build user prompt from channel message payload
- Inject channel/schema capabilities into sandbox via `_setup_capability_proxies`

In `_setup_capability_proxies()`:
- Add support for `ChannelsCapability` and `SchemasCapability` handlers
- Create implicit process channel if not exists
- Pass `ProcessHandle` for `procs` capability (for spawn integration)

In `handler()`:
- After run completes, emit lifecycle message to `system:lifecycle` channel instead of calling `repo.append_event()`

**Step 2: Write test for executor with channels**

```python
"""Test executor uses channel messages instead of events."""
# Verify that:
# 1. Channel message payload is passed to process as context
# 2. Channels capability is injected when bound
# 3. Lifecycle messages go to system:lifecycle channel
```

**Step 3: Run tests**

Run: `python -m pytest tests/cogos/test_executor_channels.py tests/cogos/test_executor_handler.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/executor/handler.py tests/cogos/test_executor_channels.py
git commit -m "feat(channels): executor uses channel messages for context and lifecycle"
```

---

### Task 11: Remove Old Event Code

**Files:**
- Delete: `src/cogos/capabilities/events.py`
- Delete: `src/cogos/db/models/event.py`
- Delete: `src/cogos/db/models/event_delivery.py`
- Delete: `src/cogos/db/models/event_outbox.py`
- Delete: `src/cogos/db/models/event_type.py`
- Modify: `src/cogos/db/models/__init__.py` — remove event imports
- Modify: `src/cogos/db/local_repository.py` — remove event methods
- Modify: `src/cogos/db/repository.py` — remove event methods
- Modify: `src/cogos/capabilities/__init__.py` — remove events from BUILTIN_CAPABILITIES, add channels/schemas
- Delete: `tests/cogos/capabilities/test_events_scoping.py`
- Modify: remaining tests that reference events

**Step 1: Remove files and update imports**

Systematically remove all event-related code. Update `__init__.py` exports. Update `BUILTIN_CAPABILITIES` to replace `events` with `channels` and `schemas`.

**Step 2: Run all tests**

Run: `python -m pytest tests/cogos/ -v`
Expected: PASS (after fixing any remaining event references in tests)

**Step 3: Commit**

```bash
git add -A
git commit -m "feat(channels): remove old event system (Event, EventDelivery, EventOutbox, EventType, EventsCapability)"
```

---

### Task 12: Update I/O Bridges

**Files:**
- Modify: `src/cogos/io/discord/bridge.py`
- Create: `images/cogent-v1/files/cogos/io/discord/schema.md`
- Create: `images/cogent-v1/files/cogos/io/email/schema.md`
- Modify: `src/cogos/io/discord/capability.py`
- Modify: `src/cogos/io/email/capability.py`
- Test: `tests/cogos/io/test_discord_bridge_channels.py`

**Step 1: Create I/O schema files**

`images/cogent-v1/files/cogos/io/discord/schema.md`:
```yaml
fields:
  content: string
  author: string
  author_id: string
  channel_id: string
  guild_id: string
  message_id: string
  event_type: string
  is_dm: bool
  is_mention: bool
  attachments: list
  thread_id: string
  parent_channel_id: string
  embeds: list
  reference_message_id: string
```

`images/cogent-v1/files/cogos/io/email/schema.md`:
```yaml
fields:
  sender: string
  to: string
  subject: string
  body: string
  date: string
  message_id: string
```

**Step 2: Update Discord bridge**

In `_relay_to_db()`: instead of `repo.append_event(Event(...))`, write to the appropriate channel:
```python
channel = repo.get_channel_by_name(f"io:discord:{event_type}")
if channel is None:
    channel = Channel(name=f"io:discord:{event_type}", ...)
    repo.upsert_channel(channel)
repo.append_channel_message(ChannelMessage(channel=channel.id, ...))
```

**Step 3: Update Discord/Email capabilities**

Update `receive()` methods to read from channels instead of querying events.

**Step 4: Test**

Run: `python -m pytest tests/cogos/io/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/io/ images/cogent-v1/files/cogos/io/ tests/cogos/io/
git commit -m "feat(channels): update Discord/Email bridges to use channels"
```

---

### Task 13: Update Image Apply and Init

**Files:**
- Modify: `src/cogos/image/apply.py`
- Modify: `src/cogos/image/spec.py`
- Modify: `images/cogent-v1/init/processes.py`
- Modify: `src/cogos/capabilities/__init__.py`
- Test: `tests/cogos/test_image_apply.py`

**Step 1: Update apply_image**

- Instead of creating `Handler` rows with `event_pattern`, create channels and bind handlers to channels
- Load `.schema.md` files from `cogos/io/*/schema.md` and register as `cogos_schema` rows
- Replace `output_events` with channel creation
- Add `channels` and `schemas` to BUILTIN_CAPABILITIES

**Step 2: Update image spec**

Add `add_schema()` and `add_channel()` helpers to the spec loader.

**Step 3: Update init/processes.py**

Change handler declarations from `handlers=["discord:dm", "discord:mention"]` to channel subscriptions.

**Step 4: Run tests**

Run: `python -m pytest tests/cogos/test_image_apply.py tests/cogos/test_image_e2e.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/ images/cogent-v1/ src/cogos/capabilities/__init__.py tests/cogos/test_image_apply.py
git commit -m "feat(channels): update image apply to use channels and schemas"
```

---

### Task 14: Update Dashboard

**Files:**
- Create: `src/dashboard/routers/channels.py`
- Create: `src/dashboard/routers/schemas.py`
- Modify: `src/dashboard/routers/handlers.py`
- Delete: `src/dashboard/routers/cogos_events.py`
- Delete: `src/dashboard/routers/event_types.py`
- Modify: `src/dashboard/app.py`

**Step 1: Create channels router**

`src/dashboard/routers/channels.py`:
- `GET /channels` — list channels with owner name, message count, subscriber count
- `GET /channels/{channel_id}` — channel detail with recent messages
- `POST /channels` — create named channel
- `DELETE /channels/{channel_id}` — close channel

**Step 2: Create schemas router**

`src/dashboard/routers/schemas.py`:
- `GET /schemas` — list schemas
- `GET /schemas/{name}` — schema detail
- `POST /schemas` — create schema
- `DELETE /schemas/{name}` — delete schema

**Step 3: Update handlers router**

Replace `event_pattern` with `channel` FK. Update `HandlerOut` to show channel name. Update `_to_out` to count channel messages instead of events.

**Step 4: Update app.py**

Remove `cogos_events` and `event_types` router imports. Add `channels` and `schemas` routers.

**Step 5: Remove old routers**

Delete `cogos_events.py` and `event_types.py`.

**Step 6: Commit**

```bash
git add src/dashboard/
git commit -m "feat(channels): dashboard — channel/schema pages, remove event pages"
```

---

### Task 15: Update Documentation and Includes

**Files:**
- Modify: `images/cogent-v1/files/cogos/includes/events.md` → rename/replace with channels include
- Create: `images/cogent-v1/files/cogos/includes/channels.md`
- Modify: `images/cogent-v1/files/cogos/docs/events.md` → replace with channels doc
- Modify: `images/cogent-v1/files/cogos/includes/procs.md` — update spawn docs

**Step 1: Create channels include**

Replace event-focused instructions with channel-based instructions for LLM processes.

**Step 2: Update procs include**

Document `ProcessHandle` with send/recv/kill/wait/wait_any/wait_all.

**Step 3: Commit**

```bash
git add images/cogent-v1/files/cogos/
git commit -m "docs(channels): update LLM-facing includes and docs for channels"
```

---

### Task 16: Final Cleanup and Full Test Run

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

**Step 2: Grep for leftover event references**

Run: `grep -r "event_type\|event_pattern\|EventsCapability\|append_event\|EventOutbox\|EventDelivery\|EventType\b" src/cogos/ src/dashboard/ --include="*.py" -l`

Fix any remaining references.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore(channels): final cleanup — remove all event references"
```
