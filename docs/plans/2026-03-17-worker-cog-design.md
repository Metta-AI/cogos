# Worker Cog + Supervisor Delegation Design

## Summary

Add a worker cog (`cogos/worker/`) that the supervisor uses to create and run task-specific coglets. Add `CogRegistryCapability` for cog access, `Cog.make_coglet()` interface, rename `CogRuntime` → `CogletRuntime`, and rewrite the supervisor to screen requests for security then delegate via worker coglets.

## Flow

```
Escalation arrives on supervisor:help
  → Supervisor parses request
  → Security screen (security.md rules) — refuse + alert if threat
  → Decide: answer directly or delegate?
  → If delegate:
      worker_cog = cog_registry.get_or_make_cog("cogos/worker")
      coglet, required_caps = worker_cog.make_coglet(reason)
      # Inspect required_caps, scope them
      coglet_runtime.run(coglet, procs, capabilities=scoped_caps)
      # Notify user
```

## New: Worker Cog

```
cogos/worker/
  cog.py              # CogConfig — one_shot, all possible capabilities
  main.md             # Worker template prompt (code_mode + files + task instructions)
  make_coglet.py      # make_coglet(reason, cog_dir) -> (CogletManifest, required_caps)
```

`make_coglet.py` reads `main.md`, appends reason as `## Task`, picks capabilities based on keywords in the reason.

## New: CogRegistryCapability

`src/cogos/capabilities/cog_registry.py` — gives processes access to Cog objects.

- `get_or_make_cog(path)` — loads Cog from filesystem, caches
- Scoped by allowed paths

## New: Cog.make_coglet()

`Cog` class gains `make_coglet(reason)` which loads and executes `make_coglet.py` from the cog directory.

Returns `(CogletManifest, list[str])` — the coglet and its required capabilities.

## Rename: CogRuntime → CogletRuntime

- `run_coglet()` accepts capability overrides so supervisor can pass scoped caps
- `run_cog()` unchanged

## Supervisor Rewrite

```
cogos/supervisor/
  cog.py              # Add cog_registry, coglet_runtime to capabilities
  main.md             # Rewrite — includes security.md + delegate.md
  security.md         # Security screening rules
  delegate.md         # How to use worker_cog + coglet_runtime
```

## Files

### Create
- `images/cogent-v1/cogos/worker/cog.py`
- `images/cogent-v1/cogos/worker/main.md`
- `images/cogent-v1/cogos/worker/make_coglet.py`
- `images/cogent-v1/cogos/supervisor/security.md`
- `images/cogent-v1/cogos/supervisor/delegate.md`
- `src/cogos/capabilities/cog_registry.py`

### Modify
- `src/cogos/cog/cog.py` — add make_coglet()
- `src/cogos/cog/runtime.py` — rename CogRuntime → CogletRuntime, capability overrides on run_coglet
- `src/cogos/capabilities/registry.py` — register cog_registry
- `images/cogent-v1/cogos/supervisor/cog.py` — add cog_registry, coglet_runtime
- `images/cogent-v1/cogos/supervisor/main.md` — rewrite
- `images/cogent-v1/cogos/init.py` — wire cog_registry
