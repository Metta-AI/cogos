"""Apply an ImageSpec to a CogOS repository."""

from __future__ import annotations

import logging

from cogos.db.models import (
    Capability,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
)
from cogos.files.store import FileStore
from cogos.image.spec import ImageSpec

logger = logging.getLogger(__name__)


def apply_image(spec: ImageSpec, repo, *, clean: bool = False) -> dict[str, int]:
    """Apply an image spec to the database. Returns counts of entities created/updated."""
    counts = {"capabilities": 0, "resources": 0, "files": 0, "processes": 0, "cron": 0}

    # 1. Capabilities
    for cap_dict in spec.capabilities:
        cap = Capability(
            name=cap_dict["name"],
            handler=cap_dict["handler"],
            description=cap_dict.get("description", ""),
            instructions=cap_dict.get("instructions", ""),
            input_schema=cap_dict.get("input_schema") or {},
            output_schema=cap_dict.get("output_schema") or {},
            iam_role_arn=cap_dict.get("iam_role_arn"),
            metadata=cap_dict.get("metadata") or {},
        )
        repo.upsert_capability(cap)
        counts["capabilities"] += 1

    # 2. Files
    fs = FileStore(repo)
    for key, content in spec.files.items():
        fs.upsert(key, content, source="image")
        counts["files"] += 1

    # 3. Processes (with capability bindings and handlers)
    for proc_dict in spec.processes:
        code_id = None
        if proc_dict.get("code_key"):
            f = repo.get_file_by_key(proc_dict["code_key"])
            if f:
                code_id = f.id

        mode = ProcessMode(proc_dict.get("mode", "one_shot"))
        p = Process(
            name=proc_dict["name"],
            mode=mode,
            content=proc_dict.get("content", ""),
            code=code_id,
            runner=proc_dict.get("runner", "lambda"),
            model=proc_dict.get("model"),
            priority=float(proc_dict.get("priority", 0.0)),
            status=ProcessStatus.WAITING if mode == ProcessMode.DAEMON else ProcessStatus.RUNNABLE,
            metadata=proc_dict.get("metadata") or {},
        )
        pid = repo.upsert_process(p)

        # Bind capabilities
        for cap_name in proc_dict.get("capabilities", []):
            cap = repo.get_capability_by_name(cap_name)
            if cap:
                pc = ProcessCapability(process=pid, capability=cap.id)
                repo.create_process_capability(pc)

        # Create handlers
        for pattern in proc_dict.get("handlers", []):
            h = Handler(process=pid, event_pattern=pattern, enabled=True)
            repo.create_handler(h)

        counts["processes"] += 1

    return counts
