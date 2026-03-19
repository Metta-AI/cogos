# Mount Filesystem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat FileStore namespace with a mount-based model: `/mnt/boot/` (read-only image content), `/mnt/disk/` (persistent runtime state), `/mnt/repo/` (read-only git repo snapshot).

**Architecture:** Add `read_only` scope to `DirCapability` so `get()` returns read-only `FileCapability`. Modify `apply_image` to write files under `mnt/boot/` and `mnt/repo/` prefixes. Update `init.py` to inject `boot`, `src`, `disk`, `repo` mounts instead of `dir`/`data`/`source`. Migrate all apps.

**Tech Stack:** Python, CogOS sandbox, FileStore (DB-backed)

---

### Task 1: Add `read_only` to `DirCapability`

**Files:**
- Modify: `src/cogos/capabilities/file_cap.py:281-441`

**Step 1: Write the failing test**

Create test file `tests/cogos/capabilities/test_dir_read_only.py`:

```python
"""Tests for DirCapability read_only scope."""
import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.file_cap import DirCapability, FileCapability


def _make_dir_cap(prefix="test/", read_only=False):
    repo = MagicMock()
    cap = DirCapability(repo=repo, process_id=uuid4())
    scope = {"prefix": prefix}
    if read_only:
        scope["read_only"] = True
    cap._scope = scope
    return cap


def test_read_only_get_returns_read_only_file():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    fc = d.get("foo.txt")
    assert fc._scope["ops"] == {"read"}


def test_writable_get_returns_writable_file():
    d = _make_dir_cap(prefix="mnt/disk/myapp/", read_only=False)
    fc = d.get("foo.txt")
    assert "ops" not in fc._scope


def test_read_only_cannot_be_widened():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    child = d.scope(prefix="mnt/boot/sub/")
    assert child._scope.get("read_only") is True


def test_read_only_can_be_narrowed_from_writable():
    d = _make_dir_cap(prefix="mnt/disk/", read_only=False)
    child = d.scope(prefix="mnt/disk/sub/", read_only=True)
    assert child._scope.get("read_only") is True


def test_read_only_file_write_raises():
    repo = MagicMock()
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    fc = d.get("foo.txt")
    with pytest.raises(PermissionError, match="not permitted"):
        fc.write("hello")


def test_read_only_file_read_works():
    repo = MagicMock()
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    fc = d.get("foo.txt")
    # read() calls _check("read") which should pass with ops={"read"}
    # It will fail on FileStore lookup but that's fine — we're testing the permission check
    fc._check("read", key="mnt/boot/foo.txt")  # should not raise


def test_repr_shows_read_only():
    d = _make_dir_cap(prefix="mnt/boot/", read_only=True)
    assert "read-only" in repr(d)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/capabilities/test_dir_read_only.py -v`
Expected: FAIL — `read_only` not yet supported

**Step 3: Implement `read_only` support**

In `src/cogos/capabilities/file_cap.py`, modify `DirCapability`:

1. Update `_narrow()` to handle `read_only` (sticky — once True, stays True):

```python
def _narrow(self, existing: dict, requested: dict) -> dict:
    merged = {**existing, **requested}
    if "prefix" in existing and "prefix" in requested:
        if not requested["prefix"].startswith(existing["prefix"]):
            raise ValueError(
                f"Cannot widen prefix from {existing['prefix']!r} "
                f"to {requested['prefix']!r}"
            )
        merged["prefix"] = requested["prefix"]
    # read_only is sticky — once True, cannot be set back to False
    if existing.get("read_only"):
        merged["read_only"] = True
    return merged
```

2. Update `get()` to propagate `read_only`:

```python
def get(self, key: str) -> FileCapability:
    """Return a FileCapability scoped to the given key under this dir."""
    full_key = self._full_key(key)
    fc = FileCapability(
        repo=self.repo,
        process_id=self.process_id,
        run_id=self.run_id,
    )
    scope = {"key": full_key}
    if self._scope.get("read_only"):
        scope["ops"] = {"read"}
    fc._scope = scope
    return fc
```

3. Update `__repr__` to show read-only status:

```python
def __repr__(self) -> str:
    prefix = self._scope.get("prefix", "")
    ro = " read-only" if self._scope.get("read_only") else ""
    if prefix:
        return f"<Dir '{prefix}'{ro} list() get(key) grep(pattern) glob(pattern) tree()>"
    return f"<DirCapability{ro} list() get(key) grep(pattern) glob(pattern) tree()>"
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/capabilities/test_dir_read_only.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/cogos/capabilities/test_dir_read_only.py src/cogos/capabilities/file_cap.py
git commit -m "feat: add read_only scope to DirCapability"
```

---

### Task 2: Update `image_file_prefixes` and `apply_image` to use mount prefixes

**Files:**
- Modify: `src/cogos/image/spec.py:21-32`
- Modify: `src/cogos/image/apply.py:80-84`

**Step 1: Write the failing test**

Create test file `tests/cogos/image/test_mount_prefixes.py`:

```python
"""Tests for mount-based file prefix mapping."""
from pathlib import Path
from unittest.mock import MagicMock
from cogos.image.spec import load_image


def test_app_files_written_under_mnt_boot(tmp_path):
    """App files should be keyed under mnt/boot/ instead of apps/."""
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text("print('hello')")

    spec = load_image(tmp_path)
    assert "mnt/boot/myapp/main.py" in spec.files
    assert "apps/myapp/main.py" not in spec.files


def test_non_app_files_written_under_mnt_boot(tmp_path):
    """Non-app content dirs (cogos/, includes/) should also go under mnt/boot/."""
    inc_dir = tmp_path / "includes"
    inc_dir.mkdir()
    (inc_dir / "prompt.md").write_text("# Prompt")

    spec = load_image(tmp_path)
    assert "mnt/boot/includes/prompt.md" in spec.files
    assert "includes/prompt.md" not in spec.files
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/image/test_mount_prefixes.py -v`
Expected: FAIL — files still keyed under `apps/`

**Step 3: Update `load_image` to write under `mnt/boot/`**

In `src/cogos/image/spec.py`, modify the file key generation:

1. Non-app content directories (line 122): change `key = str(f.relative_to(image_dir))` to `key = "mnt/boot/" + str(f.relative_to(image_dir))`:

```python
# Line ~122 — non-app content files
key = "mnt/boot/" + str(f.relative_to(image_dir))
```

2. App files (line 144): change `key = str(f.relative_to(image_dir))` to prefix with `mnt/boot/`:

```python
# Line ~144 — app files
rel = str(f.relative_to(apps_dir))
key = "mnt/boot/" + rel
```

Note: app files currently get keys like `apps/discord/main.py`. After change, they become `mnt/boot/discord/main.py` (the `apps/` prefix is dropped, replaced by `mnt/boot/`).

3. Update `image_file_prefixes` to return `mnt/boot/` based prefixes:

```python
def image_file_prefixes(image_dir: Path) -> list[str]:
    """Return the file key prefixes that an image owns.

    On reload, all files under mnt/boot/ are wiped and rebuilt.
    """
    return ["mnt/boot/"]
```

4. Update cog manifest `content_prefix` from `"apps"` to `"mnt/boot"` (line ~157):

```python
spec.cogs.append(manifest.to_dict(content_prefix="mnt/boot"))
```

And for cogos/ subdirectory cogs (line ~166):

```python
spec.cogs.append(manifest.to_dict(content_prefix="mnt/boot/cogos"))
```

Wait — actually the cogos/ dir files also need remapping. Currently cogos/ files get key `cogos/supervisor/main.py`. They should become `mnt/boot/cogos/supervisor/main.py`. Let me re-examine.

The non-app content loop (lines 117-122) handles dirs like `includes/`, `cogos/`. The key is `str(f.relative_to(image_dir))` which gives `cogos/supervisor/main.py`. Change to `"mnt/boot/" + str(f.relative_to(image_dir))` gives `mnt/boot/cogos/supervisor/main.py`. The cog manifest for cogos/ cogs uses `content_prefix="cogos"`, so init reads `cogos/supervisor/main.py`. That needs to become `mnt/boot/cogos/supervisor/main.py`, so `content_prefix="mnt/boot/cogos"`.

For apps/ cogs, content_prefix is currently `"apps"`, and init reads `apps/discord/main.py`. With the new key `mnt/boot/discord/main.py`, content_prefix should be `"mnt/boot"`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/image/test_mount_prefixes.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/spec.py tests/cogos/image/test_mount_prefixes.py
git commit -m "feat: write image files under mnt/boot/ prefix"
```

---

### Task 3: Add git repo snapshot to image loading

**Files:**
- Modify: `src/cogos/image/spec.py`
- Modify: `src/cogos/image/apply.py`

**Step 1: Write the failing test**

Add to `tests/cogos/image/test_mount_prefixes.py`:

```python
import subprocess

def test_repo_files_written_under_mnt_repo(tmp_path):
    """Git repo contents should be copied under mnt/repo/."""
    # Create a minimal git repo
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# Hello")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)

    spec = load_image(tmp_path)
    assert "mnt/repo/src/main.py" in spec.files
    assert "mnt/repo/README.md" in spec.files
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/cogos/image/test_mount_prefixes.py::test_repo_files_written_under_mnt_repo -v`
Expected: FAIL

**Step 3: Add repo snapshot to `load_image`**

In `src/cogos/image/spec.py`, add a function to find the git repo root and copy tracked files:

```python
import subprocess

def _load_repo_files(image_dir: Path) -> dict[str, str]:
    """Load git-tracked files from the repo containing image_dir into mnt/repo/ keys."""
    # Find git repo root
    try:
        result = subprocess.run(
            ["git", "-C", str(image_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        repo_root = Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    # List tracked files
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True, text=True, check=True,
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
                content = full.read_text()
                files["mnt/repo/" + rel_path] = content
            except (UnicodeDecodeError, OSError):
                pass  # skip binary files
    return files
```

Then at the end of `load_image`, before `return spec`:

```python
# Load git repo snapshot
repo_files = _load_repo_files(image_dir)
spec.files.update(repo_files)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/cogos/image/test_mount_prefixes.py -v`
Expected: PASS

**Step 5: Update `image_file_prefixes` to include repo**

```python
def image_file_prefixes(image_dir: Path) -> list[str]:
    return ["mnt/boot/", "mnt/repo/"]
```

**Step 6: Commit**

```bash
git add src/cogos/image/spec.py tests/cogos/image/test_mount_prefixes.py
git commit -m "feat: add git repo snapshot under mnt/repo/"
```

---

### Task 4: Update `init.py` to inject mount capabilities

**Files:**
- Modify: `images/cogent-v1/cogos/init.py`

**Step 1: Update `_build_caps` to inject `boot`, `src`, `disk`, `repo` instead of `dir`, `data`, `source`**

Replace the `_build_caps` function. The key change is at the bottom where `dir` and `data` are injected:

```python
def _build_caps(cap_list, cog_name):
    """Build capabilities dict from a CogConfig capabilities list.

    Always returns dict(name, Capability) — no aliases, no None values.
    """
    caps = {}
    for entry in cap_list:
        if isinstance(entry, str):
            cap_obj = _cap_objects.get(entry)
            if cap_obj is not None:
                caps[entry] = cap_obj
        elif isinstance(entry, dict):
            name = entry["name"]
            alias = entry.get("alias", name)
            config = entry.get("config")
            cap_obj = _cap_objects.get(name)
            if cap_obj is not None and config and hasattr(cap_obj, "scope"):
                caps[alias] = cap_obj.scope(**config)
            elif cap_obj is not None:
                caps[alias] = cap_obj
    # Mount-based filesystem capabilities
    dir_cap = _cap_objects.get("dir")
    if dir_cap is not None and hasattr(dir_cap, "scope"):
        caps["boot"] = dir_cap.scope(prefix="mnt/boot/", read_only=True)
        caps["src"] = dir_cap.scope(prefix="mnt/boot/" + cog_name + "/", read_only=True)
        caps["disk"] = dir_cap.scope(prefix="mnt/disk/" + cog_name + "/")
        caps["repo"] = dir_cap.scope(prefix="mnt/repo/", read_only=True)
    return caps
```

**Step 2: Update `_spawn_cog` to read content from `mnt/boot/` prefix**

The `content_key` construction already uses `manifest.get("content_prefix", "apps")`. Since Task 2 changed the content_prefix in manifests to `"mnt/boot"`, this should work automatically. But verify:

```python
# In _spawn_cog, the content_key is:
prefix = manifest.get("content_prefix", "mnt/boot")  # update default
content_key = prefix + "/" + cog_name + "/" + entrypoint
```

Change the default from `"apps"` to `"mnt/boot"`.

**Step 3: Remove the `source` capability injection**

In `_spawn_cog`, remove these lines:

```python
    # Add source dir scoped to where the cog's files live in the FileStore
    dir_cap = _cap_objects.get("dir")
    if dir_cap is not None and hasattr(dir_cap, "scope"):
        caps["source"] = dir_cap.scope(prefix=prefix + "/" + cog_name + "/")
```

This is now handled by `src` in `_build_caps`.

**Step 4: Update profile write to use `mnt/disk/` path**

Change line 112:
```python
file.write("mnt/disk/whoami/profile.md", "\n".join(_profile_lines))
```

Wait — `whoami/` isn't cog-scoped, it's system-level. Let's keep it at `mnt/boot/whoami/profile.md` since it's generated at boot time and is read-only to cogs. Actually, init writes it — so it should go to a boot-visible location. Use `mnt/boot/whoami/profile.md`.

Actually, looking at it more carefully — init writes the profile using the `file` capability (not `dir`), so it bypasses the mount system. The `file` capability writes to the raw FileStore. This is fine for init. But cogs that read it need to find it. Currently `file.write("whoami/profile.md", ...)` — cogs would read it via `boot.get("whoami/profile.md")` which resolves to `mnt/boot/whoami/profile.md`. So init should write to `mnt/boot/whoami/profile.md`:

```python
file.write("mnt/boot/whoami/profile.md", "\n".join(_profile_lines))
```

**Step 5: Verify init.py is consistent**

Final `init.py` should have no references to old `cogs/`, `data/`, or `source` prefixes.

**Step 6: Commit**

```bash
git add images/cogent-v1/cogos/init.py
git commit -m "feat: inject boot/src/disk/repo mounts in init"
```

---

### Task 5: Migrate discord app

**Files:**
- Modify: `images/cogent-v1/apps/discord/main.py`
- Modify: `images/cogent-v1/apps/discord/handler/main.md`
- Modify: `images/cogent-v1/apps/discord/cog.py`

**Step 1: Update `discord/main.py`**

Current pattern:
```python
file.read("apps/discord/handler/main.md")
```

New pattern — use `src` (scoped to `mnt/boot/discord/`):
```python
src.get("handler/main.md").read()
```

But wait — `main.py` is a Python executor cog. It receives capabilities via `_build_caps`. The `src` capability is `dir.scope(prefix="mnt/boot/discord/")`. So `src.get("handler/main.md")` resolves to `mnt/boot/discord/handler/main.md` — correct.

Also update the capability passed to the handler subprocess. Currently passes `data` as `"data:dir": data`. Change to `"disk": disk`:

The orchestrator spawns the handler with capabilities. Currently:
```python
"data:dir": data
```
Change to pass `disk` (which it receives from `_build_caps`).

Read the actual file to see exact patterns before making changes.

**Step 2: Update `discord/handler/main.md`**

All references to `data.get(...)` become `disk.get(...)`.

**Step 3: Update `discord/cog.py`**

If cog.py declares `dir` or `file` in capabilities, those should remain (they're general capabilities). The mount capabilities (`boot`, `src`, `disk`, `repo`) are injected automatically by `_build_caps`, not declared in cog.py.

**Step 4: Commit**

```bash
git add images/cogent-v1/apps/discord/
git commit -m "feat: migrate discord app to mount filesystem"
```

---

### Task 6: Migrate github app

**Files:**
- Modify: `images/cogent-v1/apps/github/main.py`
- Modify: `images/cogent-v1/apps/github/scanner/main.md`
- Modify: `images/cogent-v1/apps/github/discovery/main.md`

**Step 1: Update `github/main.py`**

Replace:
- `file.read("apps/github/scanner/main.md")` → `src.get("scanner/main.md").read()`
- `file.read("apps/github/discovery/main.md")` → `src.get("discovery/main.md").read()`
- `data.get("last_scan.txt")` → `disk.get("last_scan.txt")`
- `data.get("repos.md")` → `disk.get("repos.md")`

When spawning scanner/discovery coglets, pass `disk` instead of `data`.

**Step 2: Update `github/scanner/main.md`**

Replace all `data.get(...)` → `disk.get(...)`.

Replace `file.write("whoami/source_repo.md", ...)` → `boot.get("whoami/source_repo.md").write(...)`. Wait — boot is read-only. The scanner writes to `whoami/source_repo.md` which is a system-level file. This is a special case — the scanner needs write access to update the source repo summary. Options:
- Write to `disk` instead: `disk.get("source_repo.md").write(...)` — but then other cogs can't see it.
- Give scanner a separate writable capability for this.

Simplest: write it to disk and have the profile reference it from there. Or better — this is an edge case that can be handled by having init write it. For now, just write to `disk.get("source_repo.md").write(...)` and note the migration.

**Step 3: Update `github/discovery/main.md`**

Replace all `data.get(...)` → `disk.get(...)`.

**Step 4: Commit**

```bash
git add images/cogent-v1/apps/github/
git commit -m "feat: migrate github app to mount filesystem"
```

---

### Task 7: Migrate remaining apps (diagnostics, newsfromthefront, recruiter, website)

**Files:**
- Modify: `images/cogent-v1/apps/diagnostics/main.py`
- Modify: `images/cogent-v1/apps/newsfromthefront/main.py`
- Modify: `images/cogent-v1/apps/recruiter/main.py`
- Modify: `images/cogent-v1/apps/website/main.py`

**Step 1: Diagnostics**

Replace all `data.get(...)` → `disk.get(...)`, `data.grep(...)` → `disk.grep(...)`, `data.glob(...)` → `disk.glob(...)`.

**Step 2: Newsfromthefront**

Replace all `file.read("apps/newsfromthefront/...")` → `src.get("...").read()`.
When spawning coglets, pass `disk` instead of `data`.

**Step 3: Recruiter**

Replace all `file.read("apps/recruiter/...")` → `src.get("...").read()`.
When spawning coglets, pass `disk` instead of `data`.

**Step 4: Website**

Website uses `web` capability, not filesystem. May need `disk` if it stores any state, but currently doesn't. No changes expected.

**Step 5: Commit**

```bash
git add images/cogent-v1/apps/diagnostics/ images/cogent-v1/apps/newsfromthefront/ images/cogent-v1/apps/recruiter/ images/cogent-v1/apps/website/
git commit -m "feat: migrate remaining apps to mount filesystem"
```

---

### Task 8: Update reload CLI to wipe boot/repo mounts

**Files:**
- Modify: `src/cogos/image/spec.py:21-32` (already done in Task 2)
- Modify: `src/cogos/cli/__main__.py:960-964`

**Step 1: Verify `image_file_prefixes` returns mount prefixes**

Already updated in Task 2 to return `["mnt/boot/", "mnt/repo/"]`. The reload command at line 961 calls this function and passes to `delete_files_by_prefixes`. This means on reload, all `mnt/boot/` and `mnt/repo/` files are wiped and rebuilt — exactly what we want.

Verify the `reload` command preserves `mnt/disk/` (it should, since `mnt/disk/` is not in the prefixes list).

**Step 2: Run existing reload tests if any**

Run: `python -m pytest tests/ -k "reload" -v`

**Step 3: Commit (if any changes needed)**

```bash
git commit -m "feat: reload wipes mnt/boot and mnt/repo on reboot"
```

---

### Task 9: Run full test suite and fix breakage

**Step 1: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`

**Step 2: Fix any broken tests**

Tests that reference old `apps/`, `data/`, `cogs/` file key prefixes need updating to use `mnt/boot/`, `mnt/disk/` prefixes.

**Step 3: Commit fixes**

```bash
git commit -m "fix: update tests for mount filesystem prefixes"
```
