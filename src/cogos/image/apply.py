"""Apply an ImageSpec to a CogOS repository."""

from __future__ import annotations

import json
import logging

from cogos.db.models import (
    Capability,
    Channel,
    ChannelType,
    Cron,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Resource,
    ResourceType,
    Schema,
)
from cogos.files.references import extract_file_references
from cogos.image.spec import ImageSpec

logger = logging.getLogger(__name__)


def apply_image(spec: ImageSpec, repo, *, clean: bool = False) -> dict[str, int]:
    """Apply an image spec to the database. Returns counts of entities created/updated."""
    with repo.batch():
        return _apply_image_inner(spec, repo, clean=clean)


def _apply_image_inner(spec: ImageSpec, repo, *, clean: bool = False) -> dict[str, int]:
    counts = {
        "capabilities": 0, "resources": 0, "files": 0, "processes": 0,
        "cron": 0, "schemas": 0, "channels": 0,
    }

    # 1. Capabilities
    for cap_dict in spec.capabilities:
        cap = Capability(
            name=cap_dict["name"],
            handler=cap_dict["handler"],
            description=cap_dict.get("description", ""),
            instructions=cap_dict.get("instructions", ""),
            schema=cap_dict.get("schema") or {},
            iam_role_arn=cap_dict.get("iam_role_arn"),
            metadata=cap_dict.get("metadata") or {},
        )
        repo.upsert_capability(cap)
        counts["capabilities"] += 1

    # 2. Resources
    for res_dict in spec.resources:
        r = Resource(
            name=res_dict["name"],
            resource_type=ResourceType(res_dict.get("resource_type", res_dict.get("type", "pool"))),
            capacity=float(res_dict.get("capacity", 1.0)),
            metadata=res_dict.get("metadata") or {},
        )
        repo.upsert_resource(r)
        counts["resources"] += 1

    # 3. Cron rules
    for cron_dict in spec.cron_rules:
        channel_name = cron_dict.get("channel_name") or cron_dict.get("event_type")
        if not channel_name:
            raise ValueError("cron rule missing channel_name")
        c = Cron(
            expression=cron_dict["expression"],
            channel_name=channel_name,
            payload=cron_dict.get("payload") or {},
            enabled=cron_dict.get("enabled", True),
        )
        repo.upsert_cron(c)
        counts["cron"] += 1

    # 4. Files
    if spec.files:
        bulk_entries = [
            (key, content, "image", extract_file_references(content, exclude_key=key))
            for key, content in spec.files.items()
        ]
        counts["files"] = repo.bulk_upsert_files(bulk_entries)

    # 5. Schemas
    for schema_dict in spec.schemas:
        file_id = None
        if schema_dict.get("file_key"):
            f = repo.get_file_by_key(schema_dict["file_key"])
            if f:
                file_id = f.id
        s = Schema(
            name=schema_dict["name"],
            definition=schema_dict.get("definition", {}),
            file_id=file_id,
        )
        repo.upsert_schema(s)
        counts["schemas"] += 1

    # 6. Channels
    for ch_dict in spec.channels:
        schema_id = None
        if ch_dict.get("schema"):
            s = repo.get_schema_by_name(ch_dict["schema"])
            if s:
                schema_id = s.id
        ch = Channel(
            name=ch_dict["name"],
            schema_id=schema_id,
            channel_type=ChannelType(ch_dict.get("channel_type", "named")),
            auto_close=ch_dict.get("auto_close", False),
        )
        repo.upsert_channel(ch)
        counts["channels"] += 1

    # 7. Cog manifests — write the manifest JSON for init.py to read at runtime.
    # IMPORTANT: The manifest must be written BEFORE creating the init process
    # (section 9) to avoid a race where the dispatcher picks up init before
    # the manifest is ready.
    counts["cogs"] = len(spec.cogs)
    repo.bulk_upsert_files([("mnt/boot/_boot/cog_manifests.json", json.dumps(spec.cogs, indent=2), "image", [])])

    # 9. Processes (with capability bindings and handlers)
    # IMPORTANT: This must come AFTER the boot manifest is written (section 8)
    # because the init process becomes RUNNABLE immediately and the dispatcher
    # may pick it up before apply_image returns. Init reads the manifest, so
    # it must exist before init is created.
    for proc_dict in spec.processes:
        mode = ProcessMode(proc_dict.get("mode", "one_shot"))
        p = Process(
            name=proc_dict["name"],
            mode=mode,
            content=proc_dict.get("content", ""),
            required_tags=proc_dict.get("required_tags", []),
            executor=proc_dict.get("executor", "llm"),
            model=proc_dict.get("model"),
            priority=float(proc_dict.get("priority", 0.0)),
            # Daemons start WAITING (activated by messages), except init which must boot immediately.
            # One-shot processes start RUNNABLE.
            status=(
                ProcessStatus.WAITING
                if mode == ProcessMode.DAEMON and proc_dict["name"] != "init"
                else ProcessStatus.RUNNABLE
            ),
            metadata=proc_dict.get("metadata") or {},
            idle_timeout_ms=proc_dict.get("idle_timeout_ms"),
        )
        pid = repo.upsert_process(p)

        # Bind capabilities
        for cap_entry in proc_dict.get("capabilities", []):
            if isinstance(cap_entry, dict):
                cap_name = cap_entry["name"]
                cap_config = cap_entry.get("config")
                cap_alias = cap_entry.get("alias", cap_name)
            else:
                cap_name = cap_entry
                cap_config = None
                cap_alias = cap_name
            cap = repo.get_capability_by_name(cap_name)
            if cap:
                pc = ProcessCapability(
                    process=pid, capability=cap.id,
                    name=cap_alias, config=cap_config,
                )
                repo.create_process_capability(pc)

        # Create handlers — channel-based
        for ch_name in proc_dict.get("handlers", []):
            ch = repo.get_channel_by_name(ch_name)
            if ch is None:
                ch = Channel(
                    name=ch_name,
                    channel_type=ChannelType.NAMED,
                )
                repo.upsert_channel(ch)
                ch = repo.get_channel_by_name(ch_name)
            h = Handler(process=pid, channel=ch.id, enabled=True)
            repo.create_handler(h)

        # Create per-process stdio channels
        for stream in ("stdin", "stdout", "stderr"):
            io_ch_name = f"process:{proc_dict['name']}:{stream}"
            if repo.get_channel_by_name(io_ch_name) is None:
                repo.upsert_channel(Channel(
                    name=io_ch_name, owner_process=pid, channel_type=ChannelType.NAMED,
                ))

        counts["processes"] += 1

    # 10. Ensure io channels exist
    for io_name in ("io:stdin", "io:stdout", "io:stderr"):
        if repo.get_channel_by_name(io_name) is None:
            repo.upsert_channel(Channel(name=io_name, channel_type=ChannelType.NAMED))
            counts["channels"] += 1

    # Record image boot timestamp
    repo.set_meta("image:booted_at")

    return counts
