"""EventType model — registry of known event type names for typeahead."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class EventType(BaseModel):
    name: str  # PK, e.g. "process:run:success"
    description: str = ""
    source: str = ""  # "handler", "capability", "process", "manual"
    created_at: datetime | None = None
