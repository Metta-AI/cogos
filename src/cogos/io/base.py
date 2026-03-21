from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class IOMode(str, enum.Enum):
    LIVE = "live"
    POLL = "poll"
    ON_DEMAND = "on_demand"


@dataclass
class InboundEvent:
    source: str
    message_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    raw_content: str = ""
    author: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    external_id: str | None = None
    external_url: str | None = None


class IOAdapter(ABC):
    mode: IOMode
    name: str

    def __init__(self, name: str):
        self.name = name

    async def start(self) -> None:
        """Start the IO adapter. Override in subclasses if needed."""
        return

    async def stop(self) -> None:
        """Stop the IO adapter. Override in subclasses if needed."""
        return

    @abstractmethod
    async def poll(self) -> list[InboundEvent]:
        ...

    async def send(self, message: str, target: str, **kwargs: Any) -> None:
        raise NotImplementedError(f"{self.name} does not support sending")
