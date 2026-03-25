"""ProcessCapability join table — binds capabilities to processes."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class ProcessCapability(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    epoch: int = 0
    process: UUID  # FK -> Process.id
    capability: UUID  # FK -> Capability.id
    name: str = ""  # namespace alias (e.g. "email_me"); defaults to capability name
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config", mode="before")
    @classmethod
    def _coerce_none(cls, v: Any) -> Any:
        return v if v is not None else {}
