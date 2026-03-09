"""Base capability class — all capabilities inherit from this."""

from __future__ import annotations

from uuid import UUID

from cogos.db.repository import Repository


class Capability:
    """Base class for CogOS capabilities.

    Subclasses define typed methods that processes call in the sandbox.
    Each capability is instantiated once per process session with a
    repository handle and the owning process ID.
    """

    def __init__(self, repo: Repository, process_id: UUID) -> None:
        self.repo = repo
        self.process_id = process_id
