"""CogosOperation model — log of system operations (reboot, reload, etc.)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

ALL_EPOCHS = -1  # sentinel: return records from every epoch


class CogosOperation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    epoch: int = 0
    type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
