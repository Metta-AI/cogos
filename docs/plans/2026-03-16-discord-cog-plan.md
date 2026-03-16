# Discord Cog Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the Discord message handler from a static image file into a coglet owned by a dedicated Discord cog, following the existing `add_cog` / `make_default_coglet` pattern used by recruiter and newsfromthefront.

**Architecture:** A new `discord` cog is registered via `add_cog("discord")` in an image init script. The cog's default coglet is the orchestrator that monitors handler performance and creates a `handler` child coglet containing the dispatch prompt. The handler child coglet replaces the old `discord-handle-message` process spawned directly in `init.py`.

**Tech Stack:** Python, pytest, CogOS image system (`add_cog`, `make_default_coglet`), `CogCapability.make_coglet()`, `CogletRuntimeCapability`

**Design doc:** `docs/plans/2026-03-16-discord-cog-design.md`

---

### Task 1: Create the structural test suite for the handler prompt

The test suite validates invariants of `main.md` (the handler prompt). This file ships with the image and is passed to `make_coglet` during bootstrap.

**Files:**
- Create: `images/cogent-v1/apps/discord/test_handler.py`

**Step 1: Write `test_handler.py`**

This is a standalone pytest file that reads `main.md` from the coglet's materialized file tree. When run via `pytest test_handler.py -v`, the coglet system materializes the files to a temp dir and runs this.

```python
"""Structural validation for the Discord handler prompt (main.md)."""

import re
from pathlib import Path


def _read_main():
    """Read main.md from the same directory as this test file."""
    return Path(__file__).parent.joinpath("main.md").read_text()


class TestRequiredSections:
    def test_has_flow_section(self):
        content = _read_main()
        assert "## Flow" in content

    def test_has_responding_section(self):
        content = _read_main()
        assert "## Responding" in content

    def test_has_escalation_section(self):
        content = _read_main()
        assert "## Escalation" in content

    def test_has_guidelines_section(self):
        content = _read_main()
        assert "## Guidelines" in content


class TestRequiredCapabilities:
    def test_references_discord(self):
        content = _read_main()
        assert "discord" in content.lower()

    def test_references_channels(self):
        content = _read_main()
        assert "channels" in content.lower()

    def test_references_dir(self):
        content = _read_main()
        assert "dir" in content.lower()


class TestRequiredPatterns:
    def test_has_waterline_dedup(self):
        content = _read_main()
        assert "waterline" in content.lower()

    def test_has_escalation_to_supervisor(self):
        content = _read_main()
        assert 'supervisor:help' in content

    def test_has_reply_to_pattern(self):
        content = _read_main()
        assert "reply_to" in content

    def test_minimum_length(self):
        content = _read_main()
        assert len(content) > 500, f"Prompt too short: {len(content)} chars"
```

**Step 2: Verify the test reads the current dispatch.md correctly**

Temporarily copy `dispatch.md` next to the test and run it:

Run: `cp images/cogent-v1/cogos/io/discord/dispatch.md /tmp/main.md && cd /tmp && python -c "
from pathlib import Path
Path('test_handler.py').write_text(Path('$(pwd)/images/cogent-v1/apps/discord/test_handler.py').read_text().replace('Path(__file__).parent', 'Path(\"/tmp\")'))
" && pytest /tmp/test_handler.py -v`

Expected: All tests PASS (the current dispatch.md satisfies all invariants)

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/discord/test_handler.py
git commit -m "feat(discord-cog): add structural test suite for handler prompt"
```

---

### Task 2: Create the handler prompt as `main.md`

Copy `dispatch.md` content to the new location, renamed to `main.md` to match the coglet convention.

**Files:**
- Create: `images/cogent-v1/apps/discord/handler/main.md`
- Reference: `images/cogent-v1/cogos/io/discord/dispatch.md` (source content)

**Step 1: Create `handler/main.md`**

Copy the content of `images/cogent-v1/cogos/io/discord/dispatch.md` verbatim to `images/cogent-v1/apps/discord/handler/main.md`.

**Step 2: Create `handler/test_main.py`**

Copy `images/cogent-v1/apps/discord/test_handler.py` to `images/cogent-v1/apps/discord/handler/test_main.py`. This is the version that ships inside the coglet file tree. Adjust the `_read_main()` helper — when run inside a coglet's materialized temp dir, `__file__` points to the temp dir, and `main.md` is a sibling:

```python
"""Structural validation for the Discord handler prompt (main.md)."""

from pathlib import Path


def _read_main():
    """Read main.md from the coglet's materialized file tree."""
    return Path(__file__).parent.joinpath("main.md").read_text()


class TestRequiredSections:
    def test_has_flow_section(self):
        assert "## Flow" in _read_main()

    def test_has_responding_section(self):
        assert "## Responding" in _read_main()

    def test_has_escalation_section(self):
        assert "## Escalation" in _read_main()

    def test_has_guidelines_section(self):
        assert "## Guidelines" in _read_main()


class TestRequiredCapabilities:
    def test_references_discord(self):
        assert "discord" in _read_main().lower()

    def test_references_channels(self):
        assert "channels" in _read_main().lower()

    def test_references_dir(self):
        assert "dir" in _read_main().lower()


class TestRequiredPatterns:
    def test_has_waterline_dedup(self):
        assert "waterline" in _read_main().lower()

    def test_has_escalation_to_supervisor(self):
        assert "supervisor:help" in _read_main()

    def test_has_reply_to_pattern(self):
        assert "reply_to" in _read_main()

    def test_minimum_length(self):
        content = _read_main()
        assert len(content) > 500, f"Prompt too short: {len(content)} chars"
```

**Step 3: Verify tests pass against the handler content**

Run: `cd images/cogent-v1/apps/discord/handler && pytest test_main.py -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add images/cogent-v1/apps/discord/handler/
git commit -m "feat(discord-cog): add handler coglet files (main.md + test_main.py)"
```

---

### Task 3: Write the Discord cog prompt

The cog prompt is the default coglet's entrypoint. It bootstraps the handler child coglet on first activation, and on subsequent activations reviews handler performance and proposes patches.

**Files:**
- Create: `images/cogent-v1/apps/discord/discord.md`

**Step 1: Write the cog prompt**

```markdown
@{cogos/includes/index.md}

You are the Discord cog. You own and evolve the Discord message handler.

## Your capabilities

You have: `cog` (scoped to discord), `coglet_runtime`, `discord`, `channels`, `dir` (scoped to data/discord/), `file`, `stdlib`.

## Bootstrap

On first activation, create the handler coglet if it doesn't exist:

```python
status = cog.get_coglet("handler")
if hasattr(status, "error"):
    handler_prompt = file.read("apps/discord/handler/main.md").content
    test_content = file.read("apps/discord/handler/test_main.py").content
    cog.make_coglet(
        name="handler",
        test_command="pytest test_main.py -v",
        files={
            "main.md": handler_prompt,
            "test_main.py": test_content,
        },
        entrypoint="main.md",
        mode="daemon",
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        capabilities=[
            "discord", "channels", "stdlib", "procs", "file",
            {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
        ],
        idle_timeout_ms=300000,
    )
    # Start the handler
    handler = cog.get_coglet("handler")
    coglet_runtime.run(handler, procs, subscribe=[
        "io:discord:dm", "io:discord:mention", "io:discord:message",
    ])
    print("Handler coglet created and started")
    exit()
```

## Review Cycle

When activated by `discord-cog:review` or `system:tick:hour`:

1. Check handler coglet status and recent log
2. Read recent conversation data from `data/discord/` to assess performance
3. Look for patterns that suggest improvement:
   - High escalation rate (too many messages forwarded to supervisor)
   - Repeated similar questions the handler could answer directly
   - User complaints or confusion
4. If no issues found, exit early
5. If improvement is warranted:
   - Read current handler prompt: `handler.read_file("main.md")`
   - Draft an improved version addressing the identified issues
   - Propose the patch: `handler.propose_patch(diff)`
   - If tests pass, merge: `handler.merge_patch(patch_id)`
   - Notify via Discord about what changed and why

## Guidelines

- Be conservative with patches — only change when there's clear evidence of a problem
- Never weaken escalation behavior — when in doubt, escalate
- Keep patches small and focused on one improvement at a time
- Always explain why a patch was made in the Discord notification
```

**Step 2: Commit**

```bash
git add images/cogent-v1/apps/discord/discord.md
git commit -m "feat(discord-cog): add cog orchestrator prompt"
```

---

### Task 4: Write the image init script for the Discord cog

Follow the pattern from `images/cogent-v1/apps/recruiter/init/cog.py` and `images/cogent-v1/apps/newsfromthefront/init/cog.py`.

**Files:**
- Create: `images/cogent-v1/apps/discord/init/cog.py`

**Step 1: Write the init script**

```python
# Discord cog — creates the root coglet that orchestrates Discord.
# The handler child coglet (message dispatch) is created at runtime
# by the orchestrator via cog.make_coglet().

import inspect as _inspect
from pathlib import Path

_THIS_FILE = Path(_inspect.currentframe().f_code.co_filename).resolve()
_APP_DIR = _THIS_FILE.parent.parent


def _read(rel: str) -> str:
    return (_APP_DIR / rel).read_text()


cog = add_cog("discord")
cog.make_default_coglet(
    entrypoint="main.md",
    mode="daemon",
    files={"main.md": _read("discord.md")},
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "stdlib", "cog", "coglet_runtime",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/discord/"}},
    ],
    handlers=[
        "discord-cog:review",
        "system:tick:hour",
    ],
    priority=5.0,
)
```

**Step 2: Commit**

```bash
git add images/cogent-v1/apps/discord/init/cog.py
git commit -m "feat(discord-cog): add image init script registering discord cog"
```

---

### Task 5: Remove the old `discord-handle-message` spawn from init.py

The handler is now a child coglet created by the Discord cog at runtime. Remove the static spawn from `init.py`.

**Files:**
- Modify: `images/cogent-v1/cogos/init.py:20-30` (remove discord-handle-message spawn)

**Step 1: Write failing test**

Add a test that verifies the Discord cog is registered and `discord-handle-message` is NOT in the image spec's static processes.

Create: `tests/cogos/test_discord_cog_image.py`

```python
"""Tests for the Discord cog image registration."""

from pathlib import Path

from cogos.image.spec import load_image


class TestDiscordCogImage:
    def test_discord_cog_registered(self):
        spec = load_image(Path("images/cogent-v1"))
        cog_names = {c["name"] for c in spec.cogs}
        assert "discord" in cog_names

    def test_discord_cog_has_default_coglet(self):
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        default = discord_cog["default_coglet"]
        assert default is not None
        assert default["entrypoint"] == "main.md"
        assert default["mode"] == "daemon"

    def test_discord_cog_has_handlers(self):
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        handlers = discord_cog["default_coglet"]["handlers"]
        assert "discord-cog:review" in handlers
        assert "system:tick:hour" in handlers

    def test_discord_cog_has_cog_capability(self):
        spec = load_image(Path("images/cogent-v1"))
        discord_cog = next(c for c in spec.cogs if c["name"] == "discord")
        caps = discord_cog["default_coglet"]["capabilities"]
        assert "cog" in caps

    def test_no_static_discord_handle_message(self):
        """The old discord-handle-message process should not be in init.py."""
        init_py = Path("images/cogent-v1/cogos/init.py").read_text()
        assert "discord-handle-message" not in init_py
```

**Step 2: Run the test to verify it fails**

Run: `pytest tests/cogos/test_discord_cog_image.py -v`
Expected: FAIL — `discord` cog not found (init script not yet loaded), and `discord-handle-message` still in init.py

**Step 3: Remove the discord-handle-message spawn from init.py**

In `images/cogent-v1/cogos/init.py`, delete lines 20-30:

```python
# DELETE these lines:
discord_prompt = file.read("cogos/io/discord/dispatch.md").content
procs.spawn("discord-handle-message",
    mode="daemon",
    content=discord_prompt,
    priority=10.0,
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    capabilities={
        "discord": None, "channels": None, "stdlib": None,
        "procs": None, "file": None, "data:dir": None,
    },
    subscribe=["io:discord:dm", "io:discord:mention", "io:discord:message"])
```

**Step 4: Run the tests**

Run: `pytest tests/cogos/test_discord_cog_image.py -v`
Expected: All PASS

**Step 5: Run existing cog tests to ensure no regression**

Run: `pytest tests/cogos/test_cog.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add images/cogent-v1/cogos/init.py tests/cogos/test_discord_cog_image.py
git commit -m "feat(discord-cog): remove static discord-handle-message, add image tests"
```

---

### Task 6: Verify full image apply with the Discord cog

Ensure the full image apply works with the new Discord cog registered.

**Files:**
- Modify: `tests/cogos/test_discord_cog_image.py` (add apply test)

**Step 1: Add an image apply test**

Append to `tests/cogos/test_discord_cog_image.py`:

```python
from cogos.image.apply import apply_image
from cogos.db.local_repository import LocalRepository


class TestDiscordCogApply:
    def test_apply_creates_discord_process(self, tmp_path):
        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        procs = repo.list_processes(limit=100)
        proc_names = {p.name for p in procs}
        assert "discord" in proc_names, f"Expected 'discord' process, got: {proc_names}"

    def test_apply_creates_discord_coglet(self, tmp_path):
        from cogos.cog import load_coglet_meta
        from cogos.files.store import FileStore

        spec = load_image(Path("images/cogent-v1"))
        repo = LocalRepository(str(tmp_path))
        apply_image(spec, repo)

        store = FileStore(repo)
        meta = load_coglet_meta(store, "discord", "discord")
        assert meta is not None
        assert meta.entrypoint == "main.md"
        assert meta.mode == "daemon"
```

**Step 2: Run the tests**

Run: `pytest tests/cogos/test_discord_cog_image.py -v`
Expected: All PASS

**Step 3: Run the full test suite for regressions**

Run: `pytest tests/cogos/ -v --timeout=60`
Expected: All PASS (or only pre-existing failures)

**Step 4: Commit**

```bash
git add tests/cogos/test_discord_cog_image.py
git commit -m "test(discord-cog): add image apply integration tests"
```

---

### Task 7: Clean up old dispatch.md reference

The old `dispatch.md` is still in the image file tree (loaded automatically as a file). It's now redundant since the handler content lives in `apps/discord/handler/main.md`. However, the cog prompt references it via `file.read("apps/discord/handler/main.md")` so the old path can be removed.

**Files:**
- Check: `images/cogent-v1/cogos/io/discord/dispatch.md` — verify no other code references it
- Do NOT delete yet if other processes reference it (the bridge chunking/markdown code is separate and unaffected)

**Step 1: Search for references to the old dispatch.md path**

Run: `grep -r "dispatch.md" images/ src/ tests/`

If the only reference was in `init.py` (which we already removed), the file is dead code in the image file tree.

**Step 2: If no remaining references, delete the file**

```bash
git rm images/cogent-v1/cogos/io/discord/dispatch.md
```

**Step 3: Run full test suite**

Run: `pytest tests/cogos/ -v --timeout=60`
Expected: All PASS

**Step 4: Commit**

```bash
git commit -m "chore(discord-cog): remove old dispatch.md (now lives in handler coglet)"
```
