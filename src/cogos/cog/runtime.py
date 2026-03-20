"""CogletRuntime — spawns cogs and coglets from directory structure.

Works with two kinds of cog data:
- Filesystem ``Cog`` objects (used by load_image at build time)
- Manifest dicts from FileStore (used by init.py at runtime)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from cogos.cog.cog import Cog, CogConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CogManifest — lightweight data object for runtime (no filesystem needed)
# ---------------------------------------------------------------------------

@dataclass
class CogletManifest:
    """A child coglet's manifest data."""
    name: str
    config: CogConfig
    content: str
    entrypoint: str

    def short_name(self) -> str:
        """Return a compact name suitable for use as a process name prefix."""
        return self.name


@dataclass
class CogManifest:
    """A cog's manifest — all data needed to spawn it at runtime."""
    name: str
    config: CogConfig
    content: str
    entrypoint: str
    coglets: dict[str, CogletManifest] = field(default_factory=dict)

    @classmethod
    def from_cog(cls, cog: Cog) -> CogManifest:
        """Build a manifest from a filesystem Cog."""
        coglets = {}
        for coglet_name in cog.coglets:
            ref = cog.get_coglet(coglet_name)
            coglets[coglet_name] = CogletManifest(
                name=ref.name,
                config=ref.config,
                content=ref.content,
                entrypoint=ref.entrypoint,
            )
        return cls(
            name=cog.name,
            config=cog.config,
            content=cog.main_content,
            entrypoint=cog.main_entrypoint,
            coglets=coglets,
        )

    def to_dict(self, *, content_prefix: str = "apps") -> dict:
        """Serialize to a dict for JSON storage.

        *content_prefix* is the FileStore key prefix where this cog's files
        are stored (e.g. ``"apps"`` for ``apps/mycog/main.py``).
        """
        return {
            "name": self.name,
            "config": self.config.model_dump(),
            "entrypoint": self.entrypoint,
            "content_prefix": content_prefix,
            "coglets": {
                name: {
                    "name": cl.name,
                    "config": cl.config.model_dump(),
                    "entrypoint": cl.entrypoint,
                }
                for name, cl in self.coglets.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict, file_reader) -> CogManifest:
        """Reconstruct from a serialized dict + a file reader callable.

        ``file_reader(key)`` should return file content as a string.
        """
        config = CogConfig(**data["config"])
        prefix = data.get("content_prefix", "apps")
        # Read main content from FileStore
        content_key = f"{prefix}/{data['name']}/{data['entrypoint']}"
        content = file_reader(content_key)

        coglets = {}
        for cl_name, cl_data in data.get("coglets", {}).items():
            cl_config = CogConfig(**cl_data["config"])
            cl_content_key = f"{prefix}/{data['name']}/{cl_name}/{cl_data['entrypoint']}"
            cl_content = file_reader(cl_content_key)
            coglets[cl_name] = CogletManifest(
                name=cl_name,
                config=cl_config,
                content=cl_content,
                entrypoint=cl_data["entrypoint"],
            )

        return cls(
            name=data["name"],
            config=config,
            content=content,
            entrypoint=data["entrypoint"],
            coglets=coglets,
        )


# ---------------------------------------------------------------------------
# CogletRuntime
# ---------------------------------------------------------------------------

class CogletRuntime:
    """Spawns cog main coglets and child coglets with scoped capabilities.

    Accepts either a filesystem ``Cog`` or a ``CogManifest``.
    """

    def __init__(self, manifest: CogManifest, cap_objects: dict[str, Any]) -> None:
        self.manifest = manifest
        self.cap_objects = cap_objects

    @classmethod
    def from_cog(cls, cog: Cog, cap_objects: dict[str, Any]) -> CogletRuntime:
        """Create from a filesystem Cog object."""
        return cls(CogManifest.from_cog(cog), cap_objects)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_cog(self, procs: Any) -> Any:
        """Spawn the main coglet for this cog. Returns ProcessHandle."""
        m = self.manifest
        caps = self._build_capabilities(m.config)
        self._add_scoped_dir_and_data(caps, m.name)
        caps["runtime"] = self

        return procs.spawn(
            name=m.name,
            content=m.content,
            mode=m.config.mode,
            priority=m.config.priority,
            executor=m.config.executor,
            model=m.config.model,
            runner=m.config.runner,
            idle_timeout_ms=m.config.idle_timeout_ms,
            capabilities=caps,
            subscribe=m.config.handlers if m.config.handlers else None,
            detached=True,
        )

    def run(
        self,
        name_or_manifest: str | CogletManifest,
        procs: Any,
        capabilities: dict | None = None,
        capability_overrides: dict | None = None,
    ) -> Any:
        """Spawn a child coglet by name or manifest. Returns ProcessHandle.

        If *capabilities* is provided it is used as-is instead of building
        capabilities from the coglet config.  *capability_overrides* is an
        alias accepted for backwards compatibility.
        """
        caps = capabilities or capability_overrides
        return self.run_coglet(name_or_manifest, procs, capabilities=caps)

    def run_coglet(
        self,
        name_or_manifest: str | CogletManifest,
        procs: Any,
        capabilities: dict | None = None,
    ) -> Any:
        """Spawn a child coglet by name or manifest. Returns ProcessHandle.

        If *capabilities* is provided it is used as-is instead of building
        capabilities from the coglet config.
        """
        m = self.manifest
        if isinstance(name_or_manifest, str):
            name = name_or_manifest
            cl = m.coglets.get(name)
            if cl is None:
                raise FileNotFoundError(
                    f"Coglet '{name}' not found in cog '{m.name}'"
                )
        else:
            cl = name_or_manifest
            name = cl.name

        if capabilities is not None:
            caps = dict(capabilities)
        else:
            caps = self._build_capabilities(cl.config)
            self._add_scoped_dir_and_data(caps, m.name)

        return procs.spawn(
            name=f"{m.name}/{name}",
            content=cl.content,
            mode=cl.config.mode,
            priority=cl.config.priority,
            executor=cl.config.executor,
            model=cl.config.model,
            runner=cl.config.runner,
            idle_timeout_ms=cl.config.idle_timeout_ms,
            capabilities=caps,
            subscribe=cl.config.handlers if cl.config.handlers else None,
            detached=True,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_capabilities(self, config: CogConfig) -> dict[str, Any]:
        """Build capabilities dict from config.capabilities list.

        Always returns dict(name, Capability) — no aliases, no None values.
        """
        caps: dict[str, Any] = {}
        for entry in config.capabilities:
            if isinstance(entry, str):
                cap_obj = self.cap_objects.get(entry)
                if cap_obj is not None:
                    caps[entry] = cap_obj
            elif isinstance(entry, dict):
                name = entry["name"]
                cap_type = entry.get("type", name)
                cap_config = entry.get("config")
                cap_obj = self.cap_objects.get(cap_type)
                if cap_obj is not None and cap_config and hasattr(cap_obj, "scope"):
                    caps[name] = cap_obj.scope(**cap_config)
                elif cap_obj is not None:
                    caps[name] = cap_obj
        return caps

    def _add_scoped_dir_and_data(self, caps: dict[str, Any], cog_name: str) -> None:
        """Add mount-based filesystem capabilities."""
        dir_cap = self.cap_objects.get("fs_dir")
        if dir_cap is not None and hasattr(dir_cap, "scope"):
            caps["boot"] = dir_cap.scope(prefix="mnt/boot/", read_only=True)
            caps["src"] = dir_cap.scope(prefix=f"mnt/boot/{cog_name}/", read_only=True)
            caps["disk"] = dir_cap.scope(prefix=f"mnt/disk/{cog_name}/")
            caps["repo"] = dir_cap.scope(prefix="mnt/repo/", read_only=True)
