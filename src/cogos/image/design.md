# CogOS Image: Boot, Snapshot, Restore

## Summary

Replace the hardcoded `cogos bootstrap` command with an image-based system. An image is a directory of Python scripts and files that declaratively define a cogent's initial state. Running cogents can snapshot their state into new images. Images can boot new cogents or reimage existing ones.

## Image Structure

```
images/<name>/
  init/
    capabilities.py    # add_capability() calls
    resources.py       # add_resource() calls
    processes.py       # add_process() calls
    cron.py            # add_cron() calls
  files/
    cogos/
      scheduler.md     # file key = relative path from files/
  README.md            # optional
```

No `__init__.py`. Each `.py` in `init/` is exec'd with builder functions injected into its namespace. The `files/` directory is walked separately — each file's relative path becomes its store key.

Scripts can use normal Python (loops, conditionals, imports) to generate their calls.

## Builder API

Builder functions injected into each init script:

```python
add_capability(name, *, handler, description="", instructions="", input_schema=None, output_schema=None, iam_role_arn=None, metadata=None)
add_resource(name, *, type, capacity, metadata=None)
add_process(name, *, mode="one_shot", content="", code_key=None, runner="lambda", model=None, priority=0.0, capabilities=None, handlers=None, metadata=None)
add_cron(expression, *, event_type, payload=None, enabled=True)
```

All calls accumulate into an `ImageSpec` dataclass:

```python
@dataclass
class ImageSpec:
    capabilities: list[dict]
    resources: list[dict]
    processes: list[dict]    # each has process fields + capabilities + handlers
    cron_rules: list[dict]
    files: dict[str, str]    # key -> content
```

`load_image(path) -> ImageSpec` handles exec'ing the scripts and walking the files tree.

## What Gets Captured

Config-only. An image contains:
- Capabilities (name, handler, description, schemas)
- Resources (pool definitions)
- Processes (with capability bindings and channel handlers)
- Cron rules
- Files (active version content only)

Not captured: channel messages, runs, traces, conversations, file version history. These are runtime ephemera.

## CLI Commands

```
cogent dr.alpha cogos image boot cogent-v1          # upsert image into DB
cogent dr.alpha cogos image boot cogent-v1 --clean  # wipe tables, then load
cogent dr.alpha cogos image snapshot my-snapshot     # capture running state to image
cogent dr.alpha cogos image list                     # list available images
```

## Boot Sequence

`cogent <instance> cogos image boot <name> [--clean]`

1. Run migration (`001_create_tables.sql`)
2. If `--clean`: truncate all cogos tables
3. Upsert capabilities by name
4. Upsert resources by name
5. Upsert cron rules by (expression, channel_name)
6. Upsert files via FileStore (creates if new, new version if changed, skips if unchanged)
7. Upsert processes by name, bind capabilities, create handlers

Replaces the current `cogos bootstrap` command entirely.

## Snapshot

`cogent <instance> cogos image snapshot <name>`

1. Query DB: list all capabilities, resources, processes (with capability bindings + handlers), cron rules, files (active version only)
2. Generate `init/*.py` — emit Python source with `add_*()` calls
3. Write `files/<key>` for each file in the store
4. Write `README.md` with timestamp, source cogent, summary counts

Generated images are immediately bootable.

## Code Location

- `src/cogos/image/` — `ImageSpec`, `load_image()`, `apply_image()`, `snapshot_image()`
- `src/cogos/cli/__main__.py` — `image` subgroup with `boot`, `snapshot`, `list` commands; old `bootstrap` removed
- `images/cogent-v1/init/` — migrated to `add_*()` style (rename `run.py` to `processes.py`, split capabilities from resources, rewrite as builder calls)

## Migration from Current State

The existing `images/cogent-v1/` is rewritten in-place to use the new `add_*()` format. The `cogos bootstrap` command is removed. No backward compatibility shim needed — the old format was never consumed programmatically by the CLI anyway.
