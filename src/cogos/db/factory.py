"""Repository selection helpers for local and remote CogOS runtimes."""

from __future__ import annotations

import os
from typing import Any


def create_repository(
    *,
    data_dir: str | None = None,
    resource_arn: str | None = None,
    secret_arn: str | None = None,
    database: str | None = None,
    region: str | None = None,
    client: Any | None = None,
    nudge_callback: Any | None = None,
) -> Any:
    """Create the active repository implementation for the current environment."""
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.db.sqlite_repository import SqliteRepository

        if data_dir is None:
            raise ValueError("data_dir is required for local SQLite repository")
        return SqliteRepository(data_dir, nudge_callback=nudge_callback)

    from cogos.db.repository import RdsDataApiRepository

    return RdsDataApiRepository.create(
        resource_arn=resource_arn,
        secret_arn=secret_arn,
        database=database,
        region=region,
        client=client,
        nudge_callback=nudge_callback,
    )
