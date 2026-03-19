# Mount Filesystem Design

## Goal

Replace the flat FileStore namespace with a mount-based filesystem model that separates immutable boot content from persistent runtime state.

## Mount Table

Each cog receives four scoped `DirCapability` mounts:

| Capability | Path | Access | Purpose |
|---|---|---|---|
| `boot` | `/mnt/boot/` | read-only | Full image content (all apps) |
| `src` | `/mnt/boot/<cog_name>/` | read-only | This cog's own source files |
| `disk` | `/mnt/disk/<cog_name>/` | read-write | Persistent runtime state |
| `repo` | `/mnt/repo/` | read-only | Full git repo snapshot |

## Boot Lifecycle

1. **Wipe** all files under `/mnt/boot/` and `/mnt/repo/`
2. **Copy** `images/cogent-v1/apps/*` into `/mnt/boot/` (preserving directory structure)
3. **Copy** the full git repo into `/mnt/repo/` (preserving directory structure)
4. **Spawn** each cog with `boot`, `src`, `disk`, `repo` capabilities injected

On reboot, `/mnt/boot/` and `/mnt/repo/` are always rebuilt from source. `/mnt/disk/` persists across reboots.

## Read-Only Enforcement

Add `read_only=True` scope parameter to `DirCapability`. When set:
- `DirCapability.get()` returns a `FileCapability` with `ops={"read"}` (no write/append/edit)
- List/grep/glob/tree operations work normally

Implementation in `DirCapability._narrow()`: `read_only` can only be set to `True`, never widened back to `False`.

Implementation in `DirCapability.get()`:
```python
def get(self, key: str) -> FileCapability:
    full_key = self._full_key(key)
    fc = FileCapability(repo=self.repo, process_id=self.process_id, run_id=self.run_id)
    scope = {"key": full_key}
    if self._scope.get("read_only"):
        scope["ops"] = {"read"}
    fc._scope = scope
    return fc
```

## Migration

| Current | New |
|---|---|
| `file.read("apps/<cog>/...")` | `boot.get("<cog>/...").read()` or `src.get("...").read()` |
| `dir.scope(prefix="cogs/<cog>/")` | `disk` |
| `data` (`dir.scope(prefix="data/<cog>/")`) | `disk` |
| `source` (`dir.scope(prefix="apps/<cog>/")`) | `src` |

## Changes Required

### 1. `DirCapability` — add `read_only` support

- `_narrow()`: `read_only` is sticky — once True, stays True
- `get()`: propagate `read_only` as `ops={"read"}` on child `FileCapability`

### 2. `init.py` — new mount setup

Replace `_build_caps()` injection of `dir`, `data`, `source` with:

```python
boot = dir.scope(prefix="mnt/boot/", read_only=True)
src = dir.scope(prefix="mnt/boot/" + cog_name + "/", read_only=True)
disk = dir.scope(prefix="mnt/disk/" + cog_name + "/")
repo = dir.scope(prefix="mnt/repo/", read_only=True)
```

Add boot wipe + copy steps before cog spawning:
- Delete all files with prefix `mnt/boot/`
- Copy all files from `apps/` prefix to `mnt/boot/` prefix
- Delete all files with prefix `mnt/repo/`
- Copy git repo contents into `mnt/repo/` prefix

### 3. App migration

Update apps that use `file.read("apps/...")` to use `boot.get("...").read()` or `src.get("...").read()`.

Update apps that use `data.get(...)` to use `disk.get(...)`.

### 4. Future: `/mnt/swap/`

When needed, add ephemeral per-boot scratch space:
- `swap = dir.scope(prefix="mnt/swap/<epoch_id>/<cog_name>/")`
- Epoch ID = init process run_id
- Wiped on boot (or lazily cleaned)
