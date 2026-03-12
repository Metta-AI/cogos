"""Snapshot a running cogent's state into an image directory."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _repr_val(v) -> str:
    """Format a Python value for source code output."""
    if v is None:
        return "None"
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, bool):
        return repr(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = ", ".join(f"{_repr_val(k)}: {_repr_val(val)}" for k, val in v.items())
        return "{" + items + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        items = ", ".join(_repr_val(i) for i in v)
        return "[" + items + "]"
    return repr(v)


def snapshot_image(repo, output_dir: Path, *, cogent_name: str | None = None) -> None:
    """Read DB state and generate an image directory."""
    init_dir = output_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)
    files_dir = output_dir / "files"

    # -- Capabilities --
    caps = repo.list_capabilities()
    lines = []
    for c in caps:
        parts = [f'add_capability({_repr_val(c.name)}']
        parts.append(f'    handler={_repr_val(c.handler)}')
        if c.description:
            parts.append(f'    description={_repr_val(c.description)}')
        if c.instructions:
            parts.append(f'    instructions={_repr_val(c.instructions)}')
        if c.schema:
            parts.append(f'    schema={_repr_val(c.schema)}')
        if c.iam_role_arn:
            parts.append(f'    iam_role_arn={_repr_val(c.iam_role_arn)}')
        if c.metadata:
            parts.append(f'    metadata={_repr_val(c.metadata)}')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "capabilities.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Resources --
    resources = repo.list_resources()
    lines = []
    for r in resources:
        parts = [f'add_resource({_repr_val(r.name)}']
        parts.append(f'    type={_repr_val(r.resource_type.value)}')
        parts.append(f'    capacity={_repr_val(r.capacity)}')
        if r.metadata:
            parts.append(f'    metadata={_repr_val(r.metadata)}')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "resources.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Processes --
    procs = repo.list_processes()
    lines = []
    for p in procs:
        # Get capability names
        cap_names = []
        try:
            pcs = repo.list_process_capabilities(p.id)
            for pc in pcs:
                cap = repo.get_capability(pc.capability)
                if cap:
                    cap_names.append(cap.name)
        except (AttributeError, TypeError):
            pass

        # Get handler channel names
        handler_patterns = []
        try:
            handlers = repo.list_handlers(process_id=p.id)
            for h in handlers:
                if h.channel:
                    ch = repo.get_channel(h.channel)
                    if ch:
                        handler_patterns.append(ch.name)
                elif h.event_pattern:
                    # Legacy fallback — kept for backward compat with old snapshots
                    handler_patterns.append(h.event_pattern)
        except (AttributeError, TypeError):
            pass

        # Get code_key
        code_key = None
        if p.code:
            try:
                f = repo.get_file_by_id(p.code)
                if f:
                    code_key = f.key
            except (AttributeError, TypeError):
                pass

        parts = [f'add_process({_repr_val(p.name)}']
        parts.append(f'    mode={_repr_val(p.mode.value)}')
        if p.content:
            parts.append(f'    content={_repr_val(p.content)}')
        if code_key:
            parts.append(f'    code_key={_repr_val(code_key)}')
        parts.append(f'    runner={_repr_val(p.runner)}')
        if p.model:
            parts.append(f'    model={_repr_val(p.model)}')
        parts.append(f'    priority={_repr_val(p.priority)}')
        if cap_names:
            parts.append(f'    capabilities={_repr_val(cap_names)}')
        if handler_patterns:
            parts.append(f'    handlers={_repr_val(handler_patterns)}')
        if p.metadata:
            parts.append(f'    metadata={_repr_val(p.metadata)}')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "processes.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Schemas --
    schemas = []
    if hasattr(repo, "list_schemas"):
        schemas = repo.list_schemas()
    lines = []
    for s in schemas:
        file_key = None
        if s.file_id:
            try:
                f = repo.get_file_by_id(s.file_id)
                if f:
                    file_key = f.key
            except (AttributeError, TypeError):
                pass
        parts = [f'add_schema({_repr_val(s.name)}']
        parts.append(f'    definition={_repr_val(s.definition)}')
        if file_key:
            parts.append(f'    file_key={_repr_val(file_key)}')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "schemas.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Channels --
    channels = []
    if hasattr(repo, "list_channels"):
        channels = repo.list_channels()
    lines = []
    for ch in channels:
        schema_name = None
        if ch.schema_id:
            try:
                s = repo.get_schema(ch.schema_id)
                if s:
                    schema_name = s.name
            except (AttributeError, TypeError):
                pass
        parts = [f'add_channel({_repr_val(ch.name)}']
        if schema_name:
            parts.append(f'    schema={_repr_val(schema_name)}')
        parts.append(f'    channel_type={_repr_val(ch.channel_type.value)}')
        if ch.auto_close:
            parts.append(f'    auto_close=True')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "channels.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Cron --
    cron_rules = repo.list_cron_rules()
    lines = []
    for c in cron_rules:
        parts = [f'add_cron({_repr_val(c.expression)}']
        parts.append(f'    event_type={_repr_val(c.event_type)}')
        if c.payload:
            parts.append(f'    payload={_repr_val(c.payload)}')
        if not c.enabled:
            parts.append(f'    enabled=False')
        lines.append(",\n".join(parts) + ",\n)")
    (init_dir / "cron.py").write_text("\n\n".join(lines) + "\n" if lines else "")

    # -- Files --
    file_list = repo.list_files()
    for f in file_list:
        fv = repo.get_active_file_version(f.id)
        if fv and fv.content:
            out_path = files_dir / f.key
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(fv.content)

    # -- README --
    now = datetime.utcnow().isoformat(timespec="seconds")
    source = f" from cogent `{cogent_name}`" if cogent_name else ""
    readme = (
        f"# Snapshot{source}\n\n"
        f"Generated: {now}Z\n\n"
        f"- {len(caps)} capabilities\n"
        f"- {len(resources)} resources\n"
        f"- {len(schemas)} schemas\n"
        f"- {len(channels)} channels\n"
        f"- {len(procs)} processes\n"
        f"- {len(cron_rules)} cron rules\n"
        f"- {len(file_list)} files\n"
    )
    (output_dir / "README.md").write_text(readme)
