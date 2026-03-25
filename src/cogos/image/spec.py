"""ImageSpec and loader — pure data representation of a CogOS image."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


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
    """Return the file key prefixes that an image owns.

    On reload, all files under these prefixes are wiped and rebuilt.
    ``mnt/disk/`` is persistent and never wiped.
    """
    return ["mnt/boot/", "mnt/repo/"]



_image_cache: dict[str, ImageSpec] = {}


def load_image(image_dir: Path) -> ImageSpec:
    """Load an image from a directory by exec'ing init/*.py and walking files/."""
    cache_key = str(image_dir.resolve())
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    spec = ImageSpec()

    def add_capability(
        name, *, handler, description="", instructions="", schema=None, iam_role_arn=None, metadata=None
    ):
        spec.capabilities.append(
            {
                "name": name,
                "handler": handler,
                "description": description,
                "instructions": instructions,
                "schema": schema if schema is not None else {},
                "iam_role_arn": iam_role_arn,
                "metadata": metadata if metadata is not None else {},
            }
        )

    def add_resource(name, *, type, capacity, metadata=None):
        spec.resources.append(
            {
                "name": name,
                "resource_type": type,
                "capacity": capacity,
                "metadata": metadata if metadata is not None else {},
            }
        )

    def add_process(
        name,
        *,
        mode="one_shot",
        content="",
        required_tags=None,
        executor="llm",
        model=None,
        priority=0.0,
        capabilities=None,
        handlers=None,
        metadata=None,
        idle_timeout_ms=None,
    ):
        spec.processes.append(
            {
                "name": name,
                "mode": mode,
                "content": content,
                "required_tags": required_tags if required_tags is not None else [],
                "executor": executor,
                "model": model,
                "priority": priority,
                "capabilities": capabilities if capabilities is not None else [],
                "handlers": handlers if handlers is not None else [],
                "metadata": metadata if metadata is not None else {},
                "idle_timeout_ms": idle_timeout_ms,
            }
        )

    def add_cron(expression, *, channel_name=None, event_type=None, payload=None, enabled=True):
        target_channel = channel_name or event_type
        if not target_channel:
            raise TypeError("add_cron() requires channel_name")
        spec.cron_rules.append(
            {
                "expression": expression,
                "channel_name": target_channel,
                "payload": payload if payload is not None else {},
                "enabled": enabled,
            }
        )

    def add_schema(name, *, definition, file_key=None):
        spec.schemas.append(
            {
                "name": name,
                "definition": definition,
                "file_key": file_key,
            }
        )

    def add_channel(name, *, schema=None, channel_type="named", auto_close=False):
        spec.channels.append(
            {
                "name": name,
                "schema": schema,
                "channel_type": channel_type,
                "auto_close": auto_close,
            }
        )

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
            # Ensure script is within the expected init directory
            if not py.resolve().is_relative_to(init_dir.resolve()):
                logger.warning("Skipping init script outside image dir: %s", py)
                continue
            exec(compile(py.read_text(), str(py), "exec"), builtins.copy())

    # Upload all files under the image directory to mnt/boot/.
    _SKIP_DIRS = {".git", "__pycache__"}
    for f in sorted(image_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(image_dir)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        # App files strip the apps/ prefix so apps/myapp/x → mnt/boot/myapp/x
        rel_str = str(rel)
        if rel_str.startswith("apps/"):
            rel_str = rel_str[len("apps/"):]
        key = "mnt/boot/" + rel_str
        try:
            spec.files[key] = f.read_text()
        except UnicodeDecodeError:
            continue

    # Execute app init scripts (apps/*/init/*.py)
    apps_dir = image_dir / "apps"
    if apps_dir.is_dir():
        for app_dir in sorted(apps_dir.iterdir()):
            if not app_dir.is_dir():
                continue
            app_init = app_dir / "init"
            if app_init.is_dir():
                for py in sorted(app_init.glob("*.py")):
                    if py.name.startswith("_"):
                        continue
                    # Ensure script is within the expected app init directory
                    if not py.resolve().is_relative_to(app_init.resolve()):
                        logger.warning("Skipping app init script outside app dir: %s", py)
                        continue
                    exec(compile(py.read_text(), str(py), "exec"), builtins.copy())

    # Discover cogs — directories containing main.py or main.md
    from cogos.cog.cog import Cog, _is_cog_dir
    from cogos.cog.runtime import CogManifest

    # Scan app directories for cog directories
    if apps_dir.is_dir():
        for app_dir in sorted(apps_dir.iterdir()):
            if _is_cog_dir(app_dir):
                cog = Cog(app_dir)
                manifest = CogManifest.from_cog(cog)
                spec.cogs.append(manifest.to_dict(content_prefix="mnt/boot"))

    # Scan cogos/ subdirectory for cog directories (e.g. cogos/supervisor/)
    cogos_dir = image_dir / "cogos"
    if cogos_dir.is_dir():
        for sub_dir in sorted(cogos_dir.iterdir()):
            if _is_cog_dir(sub_dir):
                cog = Cog(sub_dir)
                manifest = CogManifest.from_cog(cog)
                spec.cogs.append(manifest.to_dict(content_prefix="mnt/boot/cogos"))

    # Load git repo snapshot under mnt/repo/
    repo_files = _load_repo_files(image_dir)
    spec.files.update(repo_files)

    _image_cache[cache_key] = spec
    return spec


def _load_repo_files(image_dir: Path) -> dict[str, str]:
    """Load git-tracked files from the repo containing image_dir into mnt/repo/ keys."""
    try:
        result = subprocess.run(
            ["git", "-C", str(image_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = result.stdout.strip().split("\n")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    files = {}
    for rel_path in tracked:
        if not rel_path:
            continue
        full = repo_root / rel_path
        if full.is_file():
            try:
                files["mnt/repo/" + rel_path] = full.read_text()
            except (UnicodeDecodeError, OSError):
                pass  # skip binary files
    return files
