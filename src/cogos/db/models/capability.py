"""Capability model — defines what a process can do."""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# "schema" shadows a deprecated BaseModel v1 attribute; harmless in v2.
warnings.filterwarnings("ignore", message='Field name "schema"', category=UserWarning)


class Capability(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = ""  # hierarchical, e.g. "files/read", "procs/spawn"
    description: str = ""
    instructions: str = ""  # guidance injected into search results
    handler: str = ""  # python dotted path, e.g. "cogos.capabilities.files:read"
    schema: dict[str, Any] = Field(default_factory=dict)
    iam_role_arn: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
