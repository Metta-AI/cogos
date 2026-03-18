"""CogRuntime — spawns cogs and coglets from directory structure."""

from __future__ import annotations

import logging
from typing import Any

from cogos.cog.cog import Cog, CogConfig, CogletRef

logger = logging.getLogger(__name__)


class CogRuntime:
    """Spawns cog main coglets and child coglets with scoped capabilities."""

    def __init__(self, cog: Cog, cap_objects: dict[str, Any]) -> None:
        """
        cog: a loaded Cog instance
        cap_objects: dict of capability name -> capability object
        """
        self.cog = cog
        self.cap_objects = cap_objects

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_cog(self, procs: Any) -> Any:
        """Spawn the main coglet for this cog. Returns ProcessHandle."""
        cog = self.cog
        config = cog.config
        caps = self._build_capabilities(config)

        # Scoped dir and data
        self._add_scoped_dir_and_data(caps, cog.name)

        # Main coglet gets runtime so it can launch children
        caps["runtime"] = self

        return procs.spawn(
            name=cog.name,
            content=cog.main_content,
            mode=config.mode,
            priority=config.priority,
            executor=config.executor,
            model=config.model,
            runner=config.runner,
            idle_timeout_ms=config.idle_timeout_ms,
            capabilities=caps,
            subscribe=config.handlers if config.handlers else None,
            detached=True,
        )

    def run_coglet(self, name: str, procs: Any) -> Any:
        """Spawn a child coglet by name. Returns ProcessHandle."""
        cog = self.cog
        ref: CogletRef = cog.get_coglet(name)
        config = ref.config
        caps = self._build_capabilities(config)

        # Same scoped dir and data as the parent cog
        self._add_scoped_dir_and_data(caps, cog.name)

        return procs.spawn(
            name=f"{cog.name}/{name}",
            content=ref.content,
            mode=config.mode,
            priority=config.priority,
            executor=config.executor,
            model=config.model,
            runner=config.runner,
            idle_timeout_ms=config.idle_timeout_ms,
            capabilities=caps,
            subscribe=config.handlers if config.handlers else None,
            detached=True,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_capabilities(self, config: CogConfig) -> dict[str, Any]:
        """Build capabilities dict from config.capabilities list."""
        caps: dict[str, Any] = {}
        for entry in config.capabilities:
            if isinstance(entry, str):
                caps[entry] = self.cap_objects.get(entry)
            elif isinstance(entry, dict):
                cap_name = entry["name"]
                alias = entry.get("alias", cap_name)
                cap_config = entry.get("config")
                cap_obj = self.cap_objects.get(cap_name)
                if cap_obj is not None and cap_config and hasattr(cap_obj, "scope"):
                    caps[alias] = cap_obj.scope(**cap_config)
                else:
                    caps[alias] = cap_obj
        return caps

    def _add_scoped_dir_and_data(self, caps: dict[str, Any], cog_name: str) -> None:
        """Add scoped dir and data capabilities."""
        dir_cap = self.cap_objects.get("dir")
        if dir_cap is not None and hasattr(dir_cap, "scope"):
            caps["dir"] = dir_cap.scope(prefix=f"cogs/{cog_name}/")
            caps["data"] = dir_cap.scope(prefix=f"data/{cog_name}/")
