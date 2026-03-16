# Init Process & Reboot Design

## Overview

Replace scattered `add_process()` declarations with a single `init` process (python executor) that spawns all other processes and coglets at runtime. Add cascade kill semantics, a reboot function, CLI command, and dashboard button.

## Init Process

- `executor="python"`, `mode="one_shot"`, the only process declared in the image spec
- Hard-codes spawn calls for infrastructure: scheduler, supervisor, discord-handle-message
- Hard-codes spawn calls for app root daemons: newsfromthefront, etc.
- Iterates `coglet_factory.list()`, runs all coglets with entrypoints
- Reads prompt content via `file.read(key).content`
- Completes after spawning everything
- `parent_process = None` — the root of the process tree

## Detached Processes

`procs.spawn()` gains `detached: bool = False`:
- `detached=False` (default) — `parent_process` = caller's process ID. Cascade kill includes this child.
- `detached=True` — `parent_process` = init process ID. Child survives if caller is killed.

`procs.detach(process_id)` reparents an existing child process to init.

Both look up the init process by name (`"init"`) and set `parent_process` to its ID.

## Cascade Kill

When a process is set to DISABLED, recursively disable all processes with `parent_process == that id`. Added to the repository/runtime layer so it applies everywhere.

Init's children include all detached processes. Cascade kill from init kills everything (which is what reboot wants).

## Reboot

A shared function in `src/cogos/runtime/reboot.py`:

1. Find the `init` process
2. Kill it (cascade kills all children recursively)
3. Verify all processes are DISABLED/COMPLETED
4. Clear process table + runs/deliveries/handlers/process_capabilities
5. Create fresh `init` process as RUNNABLE
6. Scheduler picks it up, init spawns everything

### CLI

`cogos reboot [-y]` calls the reboot function.

### Dashboard

`POST /api/reboot` endpoint calls the same function. "Reboot" button on the processes page.

## Image Changes

- `init/processes.py` declares only the `init` process
- App `init/*.py` files: keep channel/schema/resource/coglet declarations, remove `add_process()` calls
- New: `images/cogent-v1/init/init.py` — the boot script content (stored as a file, referenced by init process)

## What Reboot Preserves

- Files (file store)
- Coglets (stored as files)
- Channels and channel messages
- Schemas, resources, cron rules

## What Reboot Clears

- All processes
- All runs
- All deliveries
- All handlers
- All process_capabilities
