"""ImageSpec and loader — pure data representation of a CogOS image."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImageSpec:
    capabilities: list[dict] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    processes: list[dict] = field(default_factory=list)
    cron_rules: list[dict] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    schemas: list[dict] = field(default_factory=list)
    channels: list[dict] = field(default_factory=list)
    cogs: list[dict] = field(default_factory=list)


def image_file_prefixes(image_dir: Path) -> list[str]:
    """Return the top-level directory prefixes that an image owns as file keys.

    Excludes ``web/`` because runtime-published content (via ``web.publish()``)
    also lives under that prefix and must survive reloads.
    """
    _SKIP_DIRS = {"init", "apps", "web"}
    prefixes: list[str] = []
    for child in sorted(image_dir.iterdir()):
        if child.is_dir() and child.name not in _SKIP_DIRS:
            prefixes.append(child.name + "/")
    return prefixes


# Files that are configuration, not content — excluded from spec.files
_EXCLUDED_FILES = {"cog.py"}


def load_image(image_dir: Path) -> ImageSpec:
    """Load an image from a directory by exec'ing init/*.py and walking files/."""
    spec = ImageSpec()

    def add_capability(name, *, handler, description="", instructions="",
                       schema=None, iam_role_arn=None, metadata=None):
        spec.capabilities.append({
            "name": name, "handler": handler, "description": description,
            "instructions": instructions, "schema": schema,
            "iam_role_arn": iam_role_arn,
            "metadata": metadata,
        })

    def add_resource(name, *, type, capacity, metadata=None):
        spec.resources.append({
            "name": name, "resource_type": type, "capacity": capacity,
            "metadata": metadata or {},
        })

    def add_process(name, *, mode="one_shot", content="",
                    runner="lambda", executor="llm", model=None, priority=0.0,
                    capabilities=None, handlers=None,
                    metadata=None, idle_timeout_ms=None):
        spec.processes.append({
            "name": name, "mode": mode, "content": content,
            "runner": runner, "executor": executor, "model": model,
            "priority": priority, "capabilities": capabilities or [],
            "handlers": handlers or [],
            "metadata": metadata or {},
            "idle_timeout_ms": idle_timeout_ms,
        })

    def add_cron(expression, *, channel_name=None, event_type=None, payload=None, enabled=True):
        target_channel = channel_name or event_type
        if not target_channel:
            raise TypeError("add_cron() requires channel_name")
        spec.cron_rules.append({
            "expression": expression,
            "channel_name": target_channel,
            "payload": payload or {}, "enabled": enabled,
        })

    def add_schema(name, *, definition, file_key=None):
        spec.schemas.append({
            "name": name, "definition": definition, "file_key": file_key,
        })

    def add_channel(name, *, schema=None, channel_type="named", auto_close=False):
        spec.channels.append({
            "name": name, "schema": schema, "channel_type": channel_type,
            "auto_close": auto_close,
        })

    def add_file(key, *, content=""):
        spec.files[key] = content

    builtins = {
        "__builtins__": __builtins__,
        "add_capability": add_capability,
        "add_resource": add_resource,
        "add_process": add_process,
        "add_cron": add_cron,
        "add_schema": add_schema,
        "add_channel": add_channel,
        "add_file": add_file,
    }

    # Load top-level init scripts
    init_dir = image_dir / "init"
    if init_dir.is_dir():
        for py in sorted(init_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            exec(compile(py.read_text(), str(py), "exec"), builtins.copy())

    # Load top-level files from known content directories.
    # Directories named init/ and apps/ are structural — everything else is content.
    _STRUCTURAL_DIRS = {"init", "apps"}
    for child in sorted(image_dir.iterdir()):
        if child.is_dir() and child.name not in _STRUCTURAL_DIRS:
            for f in sorted(child.rglob("*")):
                if f.is_file() and f.name not in _EXCLUDED_FILES:
                    key = str(f.relative_to(image_dir))
                    spec.files[key] = f.read_text()

    # Load apps — each app has init/ for scripts and everything else is files
    apps_dir = image_dir / "apps"
    if apps_dir.is_dir():
        for app_dir in sorted(apps_dir.iterdir()):
            if not app_dir.is_dir():
                continue
            # App init scripts
            app_init = app_dir / "init"
            if app_init.is_dir():
                for py in sorted(app_init.glob("*.py")):
                    if py.name.startswith("_"):
                        continue
                    exec(compile(py.read_text(), str(py), "exec"), builtins.copy())
            # App files — everything under the app dir except init/, __pycache__/, and cog.py
            for f in sorted(app_dir.rglob("*")):
                rel_parts = f.relative_to(app_dir).parts
                if (f.is_file()
                    and "init" not in rel_parts
                    and "__pycache__" not in rel_parts
                    and f.name not in _EXCLUDED_FILES):
                    key = str(f.relative_to(image_dir))
                    spec.files[key] = f.read_text()

    # Discover cogs — directories containing main.py or main.md
    from cogos.cog.cog import Cog, _is_cog_dir
    from cogos.cog.runtime import CogManifest

    # Scan app directories for cog directories
    if apps_dir.is_dir():
        for app_dir in sorted(apps_dir.iterdir()):
            if _is_cog_dir(app_dir):
                cog = Cog(app_dir)
                manifest = CogManifest.from_cog(cog)
                spec.cogs.append(manifest.to_dict(content_prefix="apps"))

    # Scan cogos/ subdirectory for cog directories (e.g. cogos/supervisor/)
    cogos_dir = image_dir / "cogos"
    if cogos_dir.is_dir():
        for sub_dir in sorted(cogos_dir.iterdir()):
            if _is_cog_dir(sub_dir):
                cog = Cog(sub_dir)
                manifest = CogManifest.from_cog(cog)
                spec.cogs.append(manifest.to_dict(content_prefix="cogos"))

    return spec
