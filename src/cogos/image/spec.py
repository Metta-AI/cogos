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


def load_image(image_dir: Path) -> ImageSpec:
    """Load an image from a directory by exec'ing init/*.py and walking files/."""
    spec = ImageSpec()

    def add_capability(name, *, handler, description="", instructions="",
                       schema=None, iam_role_arn=None, metadata=None,
                       event_types=None):
        spec.capabilities.append({
            "name": name, "handler": handler, "description": description,
            "instructions": instructions, "schema": schema,
            "iam_role_arn": iam_role_arn,
            "metadata": metadata, "event_types": event_types or [],
        })

    def add_resource(name, *, type, capacity, metadata=None):
        spec.resources.append({
            "name": name, "resource_type": type, "capacity": capacity,
            "metadata": metadata or {},
        })

    def add_process(name, *, mode="one_shot", content="", code_key=None,
                    runner="lambda", model=None, priority=0.0,
                    capabilities=None, handlers=None, output_events=None,
                    metadata=None):
        spec.processes.append({
            "name": name, "mode": mode, "content": content,
            "code_key": code_key, "runner": runner, "model": model,
            "priority": priority, "capabilities": capabilities or [],
            "handlers": handlers or [], "output_events": output_events or [],
            "metadata": metadata or {},
        })

    def add_cron(expression, *, event_type, payload=None, enabled=True):
        spec.cron_rules.append({
            "expression": expression, "event_type": event_type,
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

    builtins = {
        "__builtins__": __builtins__,
        "add_capability": add_capability,
        "add_resource": add_resource,
        "add_process": add_process,
        "add_cron": add_cron,
        "add_schema": add_schema,
        "add_channel": add_channel,
    }

    init_dir = image_dir / "init"
    if init_dir.is_dir():
        for py in sorted(init_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            exec(compile(py.read_text(), str(py), "exec"), builtins.copy())

    files_dir = image_dir / "files"
    if files_dir.is_dir():
        for f in sorted(files_dir.rglob("*")):
            if f.is_file():
                key = str(f.relative_to(files_dir))
                spec.files[key] = f.read_text()

    return spec
