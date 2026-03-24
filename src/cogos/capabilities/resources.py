"""Resource capabilities — check resource availability."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class ResourceStatus(BaseModel):
    id: str
    name: str = ""
    capacity: float = 0.0
    used: float = 0.0
    remaining: float = 0.0
    available: bool = True


class ResourceCheckResult(BaseModel):
    resources: list[ResourceStatus] = []
    available: bool = True


class ResourceError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class ResourcesCapability(Capability):
    """Resource pool management.

    Usage:
        resources.check()
    """

    def check(self) -> ResourceCheckResult | ResourceError:
        """Check availability of resources bound to this process."""
        proc = self.repo.get_process(self.process_id)
        if proc is None:
            return ResourceError(error="process not found")

        if not proc.resources:
            return ResourceCheckResult()

        results = []
        all_available = True
        for resource_id in proc.resources:
            rows = self.repo.query(
                """SELECT COALESCE(SUM(amount), 0) AS used
                   FROM cogos_resource_usage ru
                   JOIN cogos_run r ON r.id = ru.run
                   WHERE ru.resource = :resource_id AND r.status = 'running'""",
                {"resource_id": resource_id},
            )
            used = float(rows[0]["used"]) if rows else 0.0

            res_rows = self.repo.query(
                "SELECT * FROM cogos_resource WHERE id = :id",
                {"id": resource_id},
            )
            if not res_rows:
                results.append(ResourceStatus(id=str(resource_id), available=False))
                all_available = False
                continue

            res = res_rows[0]
            capacity = float(res.get("capacity", 0))
            remaining = capacity - used
            available = remaining > 0

            if not available:
                all_available = False

            results.append(ResourceStatus(
                id=str(resource_id),
                name=res.get("name", ""),
                capacity=capacity,
                used=used,
                remaining=remaining,
                available=available,
            ))

        return ResourceCheckResult(resources=results, available=all_available)

    def __repr__(self) -> str:
        return "<ResourcesCapability check()>"
