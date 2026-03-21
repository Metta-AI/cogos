"""Schemas capability — load and list schema definitions."""
from __future__ import annotations

import fnmatch
from typing import Any

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
