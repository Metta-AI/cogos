"""Directory-based Cog: loads cog configuration and entrypoints from the filesystem."""

from __future__ import annotations

import glob as _glob
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ENTRYPOINT_NAMES = ("main.py", "main.md")


# ---------------------------------------------------------------------------
# Model helpers — avoid hardcoding Bedrock model IDs
# ---------------------------------------------------------------------------

_MODELS = {
    "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "opus": "us.anthropic.claude-opus-4-20250514-v1:0",
}


def model(name: str) -> str:
    """Return the Bedrock model ID for a short model name.

    >>> model("sonnet")
    'us.anthropic.claude-sonnet-4-20250514-v1:0'
    """
    if name in _MODELS:
        return _MODELS[name]
    raise ValueError(f"Unknown model {name!r}, choose from: {', '.join(_MODELS)}")


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------

class CogConfig(BaseModel):
    mode: str = "one_shot"
    priority: float = 0.0
    executor: str = "llm"  # "llm" | "python" | "agent_sdk"
    model: str | None = None
    required_tags: list[str] = Field(default_factory=list)
    capabilities: list = Field(default_factory=list)
    handlers: list[str] = Field(default_factory=list)
    idle_timeout_ms: int | None = None
    emoji: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config(path: Path) -> CogConfig:
    """Execute ``cog.py`` in *path* and return the ``config`` variable.

    If ``cog.py`` does not exist, return a default :class:`CogConfig`.
    """
    cog_py = path / "cog.py"
    if not cog_py.exists():
        return CogConfig()

    # Validate the file is within the expected directory (no path traversal)
    try:
        cog_py.resolve().relative_to(path.resolve())
    except ValueError:
        raise ValueError(f"cog.py path escapes its cog directory: {cog_py}")

    ns: dict[str, Any] = {}
    exec(compile(cog_py.read_text(), str(cog_py), "exec"), ns)  # noqa: S102

    config = ns.get("config")
    if config is None:
        raise ValueError(f"{cog_py} does not define a 'config' variable")
    if not isinstance(config, CogConfig):
        raise TypeError(
            f"{cog_py}: 'config' must be a CogConfig instance, got {type(config).__name__}"
        )
    return config


def _find_entrypoint(path: Path) -> tuple[str, str]:
    """Return ``(filename, content)`` for the first matching entrypoint in *path*.

    Raises :class:`FileNotFoundError` if neither ``main.py`` nor ``main.md`` exists.
    """
    for name in _ENTRYPOINT_NAMES:
        ep = path / name
        if ep.exists():
            return name, ep.read_text()
    raise FileNotFoundError(
        f"No entrypoint (main.py or main.md) found in {path}"
    )


def _is_cog_dir(path: Path) -> bool:
    """Return True if *path* is a directory containing an entrypoint."""
    if not path.is_dir():
        return False
    return any((path / name).exists() for name in _ENTRYPOINT_NAMES)


# ---------------------------------------------------------------------------
# CogletRef
# ---------------------------------------------------------------------------

class CogletRef:
    """Reference to a coglet subdirectory inside a cog."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.name = self.path.name
        self.config = _load_config(self.path)
        self.entrypoint, self.content = _find_entrypoint(self.path)

    def __repr__(self) -> str:
        return f"CogletRef({self.name!r})"


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Cog:
    """A cog loaded from a filesystem directory."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Cog directory does not exist: {self.path}")
        self.name = self.path.name
        self.config = _load_config(self.path)
        self.main_entrypoint, self.main_content = _find_entrypoint(self.path)

    @property
    def coglets(self) -> list[str]:
        """Return names of subdirectories that contain an entrypoint."""
        return sorted(
            d.name for d in self.path.iterdir() if _is_cog_dir(d)
        )

    def get_coglet(self, name: str) -> CogletRef:
        """Return a :class:`CogletRef` for the named subdirectory."""
        sub = self.path / name
        if not _is_cog_dir(sub):
            raise FileNotFoundError(f"Coglet '{name}' not found in {self.path}")
        return CogletRef(sub)

    def make_coglet(self, reason: str) -> tuple:
        """Create a dynamic coglet via the cog's make_coglet.py.

        Returns (CogletManifest, required_capabilities).
        """
        make_py = self.path / "make_coglet.py"
        if not make_py.exists():
            raise FileNotFoundError(
                f"Cog '{self.name}' does not support make_coglet (no make_coglet.py)"
            )
        ns: dict = {}
        exec(compile(make_py.read_text(), str(make_py), "exec"), ns)  # noqa: S102
        fn = ns.get("make_coglet")
        if fn is None:
            raise ValueError(f"{make_py} does not define a 'make_coglet' function")
        return fn(reason, cog_dir=self.path)

    def __repr__(self) -> str:
        return f"Cog({self.name!r})"


# ---------------------------------------------------------------------------
# resolve_cog_paths
# ---------------------------------------------------------------------------

def resolve_cog_paths(
    patterns: list[str],
    base_dir: Path | str,
) -> list[Path]:
    """Expand glob *patterns* relative to *base_dir* and return cog directories.

    A directory qualifies as a cog if it contains ``main.py`` or ``main.md``.
    """
    base = Path(base_dir)
    result: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        # If pattern is an absolute path, use it directly
        anchor = Path(pattern)
        if anchor.is_absolute():
            matches = [Path(p) for p in _glob.glob(str(anchor))]
        else:
            matches = [Path(p) for p in _glob.glob(str(base / pattern))]
        for m in matches:
            resolved = m.resolve()
            if resolved not in seen and _is_cog_dir(m):
                seen.add(resolved)
                result.append(m)
    return sorted(result, key=lambda p: p.name)
