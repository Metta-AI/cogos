# Recruiter Coglets Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the coglet system with runtime execution (`run()`) and CogletMeta runtime fields, then migrate the recruiter app from file-based prompts/config to six coglets.

**Architecture:** Extend CogletMeta with entrypoint/capabilities/mode fields, add `run()` to CogletCapability that delegates to `procs.spawn()`, extend `add_coglet()` image spec to accept runtime fields, then replace the recruiter's `apps/recruiter/` files and process definitions with coglet declarations. Validation tests use the python executor (no subprocess).

**Tech Stack:** Python, Pydantic, CogOS Capability base class, FileStore, SandboxExecutor for test validation.

**Reference:** Read `docs/coglet/design.md` and `docs/coglet/recruiter-migration.md` for design specs.

---

### Task 1: Extend CogletMeta with Runtime Fields

**Files:**
- Modify: `src/cogos/coglet/__init__.py:46-54`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

Add to `tests/cogos/test_coglet.py`:

```python
def test_coglet_meta_runtime_fields():
    from cogos.coglet import CogletMeta
    meta = CogletMeta(
        name="test",
        test_command="python tests/validate.py",
        entrypoint="main.md",
        process_executor="llm",
        model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        capabilities=["me", "procs", {"name": "dir", "alias": "data", "config": {"prefix": "data/"}}],
        mode="daemon",
        idle_timeout_ms=30000,
    )
    assert meta.entrypoint == "main.md"
    assert meta.process_executor == "llm"
    assert meta.model is not None
    assert len(meta.capabilities) == 3
    assert meta.mode == "daemon"
    assert meta.idle_timeout_ms == 30000


def test_coglet_meta_runtime_defaults():
    from cogos.coglet import CogletMeta
    meta = CogletMeta(name="data-only", test_command="python validate.py")
    assert meta.entrypoint is None
    assert meta.process_executor == "llm"
    assert meta.model is None
    assert meta.capabilities == []
    assert meta.mode == "one_shot"
    assert meta.idle_timeout_ms is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_coglet_meta_runtime_fields -v -x`
Expected: FAIL — `TypeError: unexpected keyword argument 'entrypoint'`

**Step 3: Write minimal implementation**

In `src/cogos/coglet/__init__.py`, modify the `CogletMeta` class (around line 46) to add new fields:

```python
class CogletMeta(BaseModel):
    id: str = Field(default_factory=_new_uuid)
    name: str
    test_command: str
    executor: str = "subprocess"
    timeout_seconds: int = 60
    version: int = 0
    created_at: str = Field(default_factory=_now_iso)
    patches: dict[str, PatchInfo] = Field(default_factory=dict)
    # Runtime execution fields
    entrypoint: str | None = None
    process_executor: str = "llm"
    model: str | None = None
    capabilities: list = Field(default_factory=list)
    mode: str = "one_shot"
    idle_timeout_ms: int | None = None
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (all existing + 2 new)

**Step 5: Commit**

```bash
git add src/cogos/coglet/__init__.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add runtime fields to CogletMeta (entrypoint, capabilities, mode)"
```

---

### Task 2: Extend add_coglet() and apply_image for Runtime Fields

**Files:**
- Modify: `src/cogos/image/spec.py:87-91`
- Modify: `src/cogos/image/apply.py` (coglets section)
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
def test_add_coglet_with_runtime_fields():
    from cogos.image.spec import ImageSpec
    spec = ImageSpec()
    spec.coglets.append({
        "name": "test-runner",
        "test_command": "python tests/validate.py",
        "files": {"main.md": "# Hello", "tests/validate.py": "print('PASS')"},
        "entrypoint": "main.md",
        "process_executor": "llm",
        "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "capabilities": ["me", "procs"],
        "mode": "daemon",
    })
    assert spec.coglets[0]["entrypoint"] == "main.md"


def test_apply_image_coglet_preserves_runtime_fields(tmp_path):
    from cogos.db.local_repository import LocalRepository
    from cogos.image.spec import ImageSpec
    from cogos.image.apply import apply_image
    from cogos.files.store import FileStore
    from cogos.capabilities.coglet_factory import _load_meta
    import json

    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(coglets=[{
        "name": "test-runner",
        "test_command": "python tests/validate.py",
        "files": {"main.md": "# Hello", "tests/validate.py": "print('PASS')"},
        "entrypoint": "main.md",
        "process_executor": "llm",
        "capabilities": ["me", "procs"],
        "mode": "daemon",
        "idle_timeout_ms": 30000,
    }])
    apply_image(spec, repo)

    store = FileStore(repo)
    meta_files = store.list_files(prefix="coglets/")
    coglet_id = None
    for f in meta_files:
        if f.key.endswith("/meta.json"):
            coglet_id = f.key.split("/")[1]
            break
    assert coglet_id is not None

    meta = _load_meta(store, coglet_id)
    assert meta.entrypoint == "main.md"
    assert meta.process_executor == "llm"
    assert meta.capabilities == ["me", "procs"]
    assert meta.mode == "daemon"
    assert meta.idle_timeout_ms == 30000
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_apply_image_coglet_preserves_runtime_fields -v -x`
Expected: FAIL — runtime fields not passed through to CogletMeta

**Step 3: Write minimal implementation**

Update `add_coglet` in `src/cogos/image/spec.py` (line 87):

```python
    def add_coglet(name, *, test_command, files, executor="subprocess", timeout_seconds=60,
                   entrypoint=None, process_executor="llm", model=None,
                   capabilities=None, mode="one_shot", idle_timeout_ms=None):
        spec.coglets.append({
            "name": name, "test_command": test_command, "files": files,
            "executor": executor, "timeout_seconds": timeout_seconds,
            "entrypoint": entrypoint, "process_executor": process_executor,
            "model": model, "capabilities": capabilities or [],
            "mode": mode, "idle_timeout_ms": idle_timeout_ms,
        })
```

Update the coglets section in `src/cogos/image/apply.py` to pass the new fields when creating `CogletMeta`:

```python
        meta = CogletMeta(
            name=name,
            test_command=test_command,
            executor=executor,
            timeout_seconds=timeout_seconds,
            entrypoint=coglet_dict.get("entrypoint"),
            process_executor=coglet_dict.get("process_executor", "llm"),
            model=coglet_dict.get("model"),
            capabilities=coglet_dict.get("capabilities") or [],
            mode=coglet_dict.get("mode", "one_shot"),
            idle_timeout_ms=coglet_dict.get("idle_timeout_ms"),
        )
```

And for the existing coglet update path, also update the runtime fields:

```python
        if existing_id:
            meta = _load_meta(fs, existing_id)
            write_file_tree(fs, existing_id, "main", files)
            meta.test_command = test_command
            meta.executor = executor
            meta.timeout_seconds = timeout_seconds
            meta.entrypoint = coglet_dict.get("entrypoint")
            meta.process_executor = coglet_dict.get("process_executor", "llm")
            meta.model = coglet_dict.get("model")
            meta.capabilities = coglet_dict.get("capabilities") or []
            meta.mode = coglet_dict.get("mode", "one_shot")
            meta.idle_timeout_ms = coglet_dict.get("idle_timeout_ms")
            _save_meta(fs, meta)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/image/spec.py src/cogos/image/apply.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): pass runtime fields through add_coglet() and apply_image"
```

---

### Task 3: Add run() to CogletCapability

**Files:**
- Modify: `src/cogos/capabilities/coglet.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
def test_coglet_run_returns_process_handle(tmp_path):
    from uuid import uuid4
    from cogos.db.local_repository import LocalRepository
    from cogos.capabilities.coglet_factory import CogletFactoryCapability
    from cogos.capabilities.coglet import CogletCapability
    from cogos.capabilities.procs import ProcsCapability
    from cogos.image.spec import ImageSpec
    from cogos.image.apply import apply_image

    repo = LocalRepository(str(tmp_path))
    # Need procs capability registered
    spec = ImageSpec(capabilities=[
        {"name": "procs", "handler": "cogos.capabilities.procs:ProcsCapability",
         "description": "Process management", "instructions": "", "schema": None,
         "iam_role_arn": None, "metadata": None},
    ])
    apply_image(spec, repo)

    pid = uuid4()
    factory = CogletFactoryCapability(repo, pid)

    # Create an executable coglet
    from cogos.capabilities.coglet_factory import _load_meta, _save_meta
    from cogos.files.store import FileStore
    created = factory.create(
        name="runnable",
        test_command="python tests/validate.py",
        files={
            "main.md": "You are a test process. Say hello.",
            "tests/validate.py": "assert len(open('main.md').read()) > 10\nprint('PASS')",
        },
    )
    # Set runtime fields on meta
    store = FileStore(repo)
    meta = _load_meta(store, created.coglet_id)
    meta.entrypoint = "main.md"
    meta.process_executor = "llm"
    meta.mode = "one_shot"
    _save_meta(store, meta)

    # Set up capabilities for run
    tendril = CogletCapability(repo, pid)
    tendril._scope = {"coglet_id": created.coglet_id}
    procs = ProcsCapability(repo, pid)

    result = tendril.run(procs)
    # Should return a ProcessHandle (has .name attribute)
    assert hasattr(result, "name") or hasattr(result, "id")
    assert not hasattr(result, "error")


def test_coglet_run_fails_without_entrypoint(tmp_path):
    from uuid import uuid4
    from cogos.db.local_repository import LocalRepository
    from cogos.capabilities.coglet_factory import CogletFactoryCapability
    from cogos.capabilities.coglet import CogletCapability
    from cogos.capabilities.procs import ProcsCapability

    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    factory = CogletFactoryCapability(repo, pid)

    created = factory.create(
        name="data-only",
        test_command="python -c 'print(1)'",
        files={"data.json": "{}"},
    )

    tendril = CogletCapability(repo, pid)
    tendril._scope = {"coglet_id": created.coglet_id}
    procs = ProcsCapability(repo, pid)

    result = tendril.run(procs)
    assert hasattr(result, "error")
    assert "entrypoint" in result.error.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_coglet_run_returns_process_handle -v -x`
Expected: FAIL — `AttributeError: 'CogletCapability' object has no attribute 'run'`

**Step 3: Write minimal implementation**

Add to `CogletCapability` in `src/cogos/capabilities/coglet.py`, add `"run"` to `ALL_OPS`, and add the method:

```python
    def run(
        self,
        procs,
        capability_overrides: dict | None = None,
        subscribe: str | None = None,
    ):
        """Run this coglet as a CogOS process.

        Reads the entrypoint from main, creates a process via procs.spawn().
        Returns a ProcessHandle or CogletError.
        """
        self._check("run")
        coglet_id = self._coglet_id()
        store = FileStore(self.repo)

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        if not meta.entrypoint:
            return CogletError(error=f"Coglet '{meta.name}' has no entrypoint (data-only coglet)")

        # Read entrypoint content
        main_files = read_file_tree(store, coglet_id, "main")
        content = main_files.get(meta.entrypoint)
        if content is None:
            return CogletError(
                error=f"Entrypoint '{meta.entrypoint}' not found in coglet '{meta.name}'"
            )

        # Merge capabilities: meta defaults + overrides
        spawn_caps = {}
        for cap_entry in meta.capabilities:
            if isinstance(cap_entry, dict):
                alias = cap_entry.get("alias", cap_entry["name"])
                spawn_caps[alias] = None  # will be resolved by procs.spawn
            else:
                spawn_caps[cap_entry] = None
        if capability_overrides:
            spawn_caps.update(capability_overrides)

        return procs.spawn(
            name=meta.name,
            content=content,
            mode=meta.mode,
            model=meta.model,
            capabilities=spawn_caps,
            subscribe=subscribe,
            idle_timeout_ms=meta.idle_timeout_ms,
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/coglet.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add run() method to CogletCapability"
```

---

### Task 4: Write Validation Scripts

Create the two validation scripts that coglets will use as their test_command.

**Files:**
- Create: `src/cogos/coglet/validate_prompt.py`
- Create: `src/cogos/coglet/validate_config.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing tests**

```python
def test_validate_prompt_passes(tmp_path):
    """Prompt validation passes for well-formed markdown with sections."""
    import subprocess
    import os

    prompt_dir = tmp_path / "coglet"
    prompt_dir.mkdir()
    (prompt_dir / "main.md").write_text(
        "# Discover\n\n## Process\n1. Do things\n2. Do more things\n\n"
        "## Rules\n- Be good\n\n```python\nx = 1 + 2\n```\n"
    )
    # Copy the validate script
    from cogos.coglet.validate_prompt import validate
    errors = validate(str(prompt_dir))
    assert errors == [], f"Unexpected errors: {errors}"


def test_validate_prompt_fails_missing_entrypoint(tmp_path):
    prompt_dir = tmp_path / "coglet"
    prompt_dir.mkdir()
    # No main.md
    from cogos.coglet.validate_prompt import validate
    errors = validate(str(prompt_dir))
    assert any("main.md" in e for e in errors)


def test_validate_prompt_fails_bad_python(tmp_path):
    prompt_dir = tmp_path / "coglet"
    prompt_dir.mkdir()
    (prompt_dir / "main.md").write_text(
        "# Test\n\n## Process\n\n```python\ndef broken(\n```\n"
    )
    from cogos.coglet.validate_prompt import validate
    errors = validate(str(prompt_dir))
    assert any("syntax" in e.lower() for e in errors)


def test_validate_config_passes(tmp_path):
    config_dir = tmp_path / "coglet"
    config_dir.mkdir()
    (config_dir / "criteria.md").write_text(
        "# Criteria\n## Must-Have\n- X\n## Strong Signals\n- Y\n## Red Flags\n- Z\n"
    )
    (config_dir / "rubric.json").write_text(
        '{"github_activity": {"weight": 0.25, "signals": ["x"]}}'
    )
    (config_dir / "strategy.md").write_text("# Strategy\nDo stuff.")
    (config_dir / "diagnosis.md").write_text("# Diagnosis\n## Error Types\nStuff.")
    sourcer = config_dir / "sourcer"
    sourcer.mkdir()
    (sourcer / "github.md").write_text("# GitHub\nSearch for repos.")
    (sourcer / "twitter.md").write_text("# Twitter\nSearch for tweets.")
    (sourcer / "web.md").write_text("# Web\nSearch the web.")
    (sourcer / "substack.md").write_text("# Substack\nSearch newsletters.")

    from cogos.coglet.validate_config import validate
    errors = validate(str(config_dir))
    assert errors == [], f"Unexpected errors: {errors}"


def test_validate_config_fails_bad_json(tmp_path):
    config_dir = tmp_path / "coglet"
    config_dir.mkdir()
    (config_dir / "criteria.md").write_text("## Must-Have\n## Strong Signals\n## Red Flags\n")
    (config_dir / "rubric.json").write_text("not json")
    (config_dir / "strategy.md").write_text("ok")
    (config_dir / "diagnosis.md").write_text("ok")
    sourcer = config_dir / "sourcer"
    sourcer.mkdir()
    for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
        (sourcer / name).write_text("ok")

    from cogos.coglet.validate_config import validate
    errors = validate(str(config_dir))
    assert any("rubric.json" in e for e in errors)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_validate_prompt_passes -v -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.coglet.validate_prompt'`

**Step 3: Write minimal implementation**

```python
# src/cogos/coglet/validate_prompt.py
"""Structural validation for prompt coglets."""

import os
import re
import sys


def validate(root: str) -> list[str]:
    """Validate a prompt coglet directory. Returns list of error strings (empty = pass)."""
    errors = []

    main_path = os.path.join(root, "main.md")
    if not os.path.exists(main_path):
        errors.append("main.md not found")
        return errors

    with open(main_path) as f:
        content = f.read()

    if len(content.strip()) < 20:
        errors.append("main.md is too short (< 20 chars)")

    # Check for markdown sections
    if "## " not in content:
        errors.append("main.md has no markdown sections (## headers)")

    # Validate inline Python code blocks
    blocks = re.findall(r'```python\n(.*?)```', content, re.DOTALL)
    for i, block in enumerate(blocks):
        try:
            compile(block, f"<code-block-{i}>", "exec")
        except SyntaxError as e:
            errors.append(f"Python syntax error in code block {i}: {e}")

    return errors


if __name__ == "__main__":
    errs = validate(os.getcwd())
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")
```

```python
# src/cogos/coglet/validate_config.py
"""Structural validation for the recruiter config coglet."""

import json
import os
import sys


def validate(root: str) -> list[str]:
    """Validate the recruiter config coglet. Returns list of error strings."""
    errors = []

    # rubric.json
    rubric_path = os.path.join(root, "rubric.json")
    if not os.path.exists(rubric_path):
        errors.append("rubric.json not found")
    else:
        try:
            with open(rubric_path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                errors.append("rubric.json must be a JSON object")
        except json.JSONDecodeError as e:
            errors.append(f"rubric.json invalid JSON: {e}")

    # criteria.md
    criteria_path = os.path.join(root, "criteria.md")
    if not os.path.exists(criteria_path):
        errors.append("criteria.md not found")
    else:
        with open(criteria_path) as f:
            content = f.read()
        for section in ["## Must-Have", "## Strong Signals", "## Red Flags"]:
            if section not in content:
                errors.append(f"criteria.md missing section: {section}")

    # Required files
    for name in ["strategy.md", "diagnosis.md"]:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            errors.append(f"{name} not found")
        elif os.path.getsize(path) < 10:
            errors.append(f"{name} is too short")

    # Sourcer files
    for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
        path = os.path.join(root, "sourcer", name)
        if not os.path.exists(path):
            errors.append(f"sourcer/{name} not found")
        elif os.path.getsize(path) < 10:
            errors.append(f"sourcer/{name} is too short")

    return errors


if __name__ == "__main__":
    errs = validate(os.getcwd())
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/coglet/validate_prompt.py src/cogos/coglet/validate_config.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add structural validation scripts for prompt and config coglets"
```

---

### Task 5: Create Recruiter Coglet Declarations

Replace the file-based recruiter with coglet declarations in the image init.

**Files:**
- Create: `images/cogent-v1/apps/recruiter/init/coglets.py`
- Modify: `images/cogent-v1/apps/recruiter/init/processes.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
def test_recruiter_coglets_created_on_image_apply(tmp_path):
    """All 6 recruiter coglets are created when the image is applied."""
    from cogos.db.local_repository import LocalRepository
    from cogos.image.spec import load_image
    from cogos.image.apply import apply_image
    from cogos.files.store import FileStore
    from cogos.capabilities.coglet_factory import _load_meta
    from pathlib import Path
    import json

    repo = LocalRepository(str(tmp_path))
    image_dir = Path(__file__).resolve().parents[2] / "images" / "cogent-v1"
    spec = load_image(image_dir)
    apply_image(spec, repo)

    store = FileStore(repo)
    meta_files = store.list_files(prefix="coglets/")
    coglet_names = set()
    for f in meta_files:
        if f.key.endswith("/meta.json"):
            cid = f.key.split("/")[1]
            meta = _load_meta(store, cid)
            if meta and meta.name.startswith("recruiter-"):
                coglet_names.add(meta.name)

    expected = {
        "recruiter-orchestrator",
        "recruiter-config",
        "recruiter-discover",
        "recruiter-present",
        "recruiter-profile",
        "recruiter-evolve",
    }
    assert expected.issubset(coglet_names), f"Missing coglets: {expected - coglet_names}"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_recruiter_coglets_created_on_image_apply -v -x`
Expected: FAIL — no recruiter coglets exist yet

**Step 3: Write minimal implementation**

Create `images/cogent-v1/apps/recruiter/init/coglets.py` that declares all 6 coglets using `add_coglet()`. This file reads the prompt files from the `apps/recruiter/` directory at load time.

The file will use the existing prompt content from the `apps/recruiter/` files. Since `load_image` executes init scripts with `__builtins__` available, we can read files using `Path`.

```python
# images/cogent-v1/apps/recruiter/init/coglets.py
from pathlib import Path

_app = Path(__file__).resolve().parent.parent  # apps/recruiter/

def _read(rel_path):
    return (_app / rel_path).read_text()

# Validation scripts (embedded as strings)
_VALIDATE_PROMPT = """\
import os, re, sys

def validate(root):
    errors = []
    main_path = os.path.join(root, "main.md")
    if not os.path.exists(main_path):
        errors.append("main.md not found")
        return errors
    with open(main_path) as f:
        content = f.read()
    if len(content.strip()) < 20:
        errors.append("main.md is too short")
    if "## " not in content:
        errors.append("main.md has no sections")
    blocks = re.findall(r'```python\\n(.*?)```', content, re.DOTALL)
    for i, block in enumerate(blocks):
        try:
            compile(block, f"<block-{i}>", "exec")
        except SyntaxError as e:
            errors.append(f"syntax error in block {i}: {e}")
    return errors

if __name__ == "__main__":
    errs = validate(os.getcwd())
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")
"""

_VALIDATE_CONFIG = """\
import json, os, sys

def validate(root):
    errors = []
    rubric_path = os.path.join(root, "rubric.json")
    if not os.path.exists(rubric_path):
        errors.append("rubric.json not found")
    else:
        try:
            with open(rubric_path) as f:
                data = json.load(f)
            if not isinstance(data, dict):
                errors.append("rubric.json must be a JSON object")
        except json.JSONDecodeError as e:
            errors.append(f"rubric.json invalid JSON: {e}")
    criteria_path = os.path.join(root, "criteria.md")
    if not os.path.exists(criteria_path):
        errors.append("criteria.md not found")
    else:
        with open(criteria_path) as f:
            content = f.read()
        for section in ["## Must-Have", "## Strong Signals", "## Red Flags"]:
            if section not in content:
                errors.append(f"criteria.md missing {section}")
    for name in ["strategy.md", "diagnosis.md"]:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            errors.append(f"{name} not found")
    for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
        path = os.path.join(root, "sourcer", name)
        if not os.path.exists(path):
            errors.append(f"sourcer/{name} not found")
    return errors

if __name__ == "__main__":
    errs = validate(os.getcwd())
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    print("PASS")
"""

# ── Config coglet (data only) ────────────────────────────

add_coglet(
    name="recruiter-config",
    test_command="python tests/validate.py",
    files={
        "criteria.md": _read("criteria.md"),
        "rubric.json": _read("rubric.json"),
        "strategy.md": _read("strategy.md"),
        "diagnosis.md": _read("diagnosis.md"),
        "evolution.md": _read("evolution.md"),
        "sourcer/github.md": _read("sourcer/github.md"),
        "sourcer/twitter.md": _read("sourcer/twitter.md"),
        "sourcer/web.md": _read("sourcer/web.md"),
        "sourcer/substack.md": _read("sourcer/substack.md"),
        "tests/validate.py": _VALIDATE_CONFIG,
    },
)

# ── Executable coglets ───────────────────────────────────

add_coglet(
    name="recruiter-orchestrator",
    test_command="python tests/validate.py",
    entrypoint="main.md",
    process_executor="llm",
    mode="daemon",
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels", "secrets", "stdlib",
        "coglet_factory", "coglet",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/recruiter/"}},
    ],
    files={
        "main.md": _read("recruiter.md"),
        "tests/validate.py": _VALIDATE_PROMPT,
    },
)

add_coglet(
    name="recruiter-discover",
    test_command="python tests/validate.py",
    entrypoint="main.md",
    process_executor="llm",
    mode="one_shot",
    files={
        "main.md": _read("discover.md"),
        "tests/validate.py": _VALIDATE_PROMPT,
    },
)

add_coglet(
    name="recruiter-present",
    test_command="python tests/validate.py",
    entrypoint="main.md",
    process_executor="llm",
    mode="daemon",
    files={
        "main.md": _read("present.md"),
        "tests/validate.py": _VALIDATE_PROMPT,
    },
)

add_coglet(
    name="recruiter-profile",
    test_command="python tests/validate.py",
    entrypoint="main.md",
    process_executor="llm",
    mode="one_shot",
    files={
        "main.md": _read("profile.md"),
        "tests/validate.py": _VALIDATE_PROMPT,
    },
)

add_coglet(
    name="recruiter-evolve",
    test_command="python tests/validate.py",
    entrypoint="main.md",
    process_executor="llm",
    mode="one_shot",
    files={
        "main.md": _read("evolve.md"),
        "tests/validate.py": _VALIDATE_PROMPT,
    },
)
```

Then modify `images/cogent-v1/apps/recruiter/init/processes.py` to remove the old process/channel definitions (they're replaced by coglets). Replace the entire content with:

```python
# Recruiter processes are now managed as coglets.
# See coglets.py in this directory.
# The recruiter-orchestrator coglet is run by a boot process.

add_channel("recruiter:feedback", channel_type="named")
```

Keep the channel since existing data may reference it.

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_recruiter_coglets_created_on_image_apply -v -x`
Expected: PASS

**Step 5: Commit**

```bash
git add images/cogent-v1/apps/recruiter/init/coglets.py images/cogent-v1/apps/recruiter/init/processes.py tests/cogos/test_coglet.py
git commit -m "feat(recruiter): declare recruiter as six coglets in image init"
```

---

### Task 6: Update Orchestrator Prompt to Use Coglets

**Files:**
- Modify: `images/cogent-v1/apps/recruiter/recruiter.md`

**Step 1: Update the orchestrator prompt**

The orchestrator now uses `coglet_factory` and `coglet` capabilities instead of raw file references. Update `recruiter.md` to:

1. Remove `@{apps/recruiter/criteria.md}` and `@{apps/recruiter/strategy.md}` file references (these live in the config coglet now)
2. Add instructions to look up coglets by name via `coglet_factory.list()`
3. Replace `procs.spawn(...)` calls with `coglet.run(procs, ...)` calls
4. Add instructions to read config from the config coglet: `coglet.scope(coglet_id=config_id).read_file("criteria.md")`

The new prompt should show the orchestrator how to:
- Find coglet IDs by name: `for c in coglet_factory.list(): if c.name == "recruiter-discover": ...`
- Scope the coglet capability: `discover = coglet.scope(coglet_id=discover_id)`
- Run a coglet: `handle = discover.run(procs, capability_overrides={...})`
- Read config: `config = coglet.scope(coglet_id=config_id); criteria = config.read_file("criteria.md")`

**Step 2: Run the image load test**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_recruiter_coglets_created_on_image_apply -v -x`
Expected: PASS

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/recruiter/recruiter.md
git commit -m "feat(recruiter): update orchestrator prompt to use coglet capabilities"
```

---

### Task 7: Update Evolve Prompt to Use Patch Workflow

**Files:**
- Modify: `images/cogent-v1/apps/recruiter/evolve.md`

**Step 1: Update the evolve prompt**

Replace file write instructions with coglet patch workflow:

1. Remove `@{apps/recruiter/criteria.md}`, `@{apps/recruiter/rubric.json}`, etc. file references
2. Add instructions to read config via coglet: `config_coglet.read_file("criteria.md")`
3. Replace direct file writes with `config_coglet.propose_patch(diff)` → check `test_passed` → Discord approval → `config_coglet.merge_patch(patch_id)` or `config_coglet.discard_patch(patch_id)`
4. For prompt coglet changes: `discover_coglet.propose_patch(diff)` etc.

**Step 2: Run the image load test**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_recruiter_coglets_created_on_image_apply -v -x`
Expected: PASS

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/recruiter/evolve.md
git commit -m "feat(recruiter): update evolve prompt to use coglet patch workflow"
```

---

### Task 8: Update Remaining Prompts

Update discover.md, present.md, and profile.md to remove `@{apps/recruiter/...}` file references. These prompts will receive config content via the orchestrator at spawn time (passed as content or capability overrides), not by reading files directly.

**Files:**
- Modify: `images/cogent-v1/apps/recruiter/discover.md`
- Modify: `images/cogent-v1/apps/recruiter/present.md`
- Modify: `images/cogent-v1/apps/recruiter/profile.md`

**Step 1: Update each prompt**

For `discover.md`: Remove the `@{apps/recruiter/...}` reference lines at the top. The discovery process will receive criteria and rubric content via the orchestrator's capability overrides when spawned. Add a note: "Read criteria from the config_coglet capability: `config_coglet.read_file('criteria.md')`"

For `present.md`: Remove `@{apps/recruiter/criteria.md}` and `@{apps/recruiter/strategy.md}` references. Add equivalent coglet read instructions.

For `profile.md`: No file references to remove — this prompt is already self-contained.

**Step 2: Verify image loads**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_recruiter_coglets_created_on_image_apply -v -x`
Expected: PASS

**Step 3: Commit**

```bash
git add images/cogent-v1/apps/recruiter/discover.md images/cogent-v1/apps/recruiter/present.md images/cogent-v1/apps/recruiter/profile.md
git commit -m "feat(recruiter): update sub-process prompts to read config from coglets"
```

---

### Task 9: Full Test Suite Verification

**Step 1: Run all coglet tests**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v`
Expected: All tests pass

**Step 2: Run image tests**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_image_apply.py tests/cogos/test_image_spec.py -v`
Expected: All tests pass

**Step 3: Reload dr.alpha and verify**

Run: `USE_LOCAL_DB=1 python -m cogos.cli -c dr.alpha reload -y`
Expected: Reload shows coglet count > 0

**Step 4: Verify coglets exist**

Run: `USE_LOCAL_DB=1 python -c "
from cogos.db.factory import create_repository
from cogos.files.store import FileStore
from cogos.capabilities.coglet_factory import _load_meta
repo = create_repository()
store = FileStore(repo)
for f in store.list_files(prefix='coglets/'):
    if f.key.endswith('/meta.json'):
        cid = f.key.split('/')[1]
        meta = _load_meta(store, cid)
        if meta: print(f'{meta.name}: v{meta.version}, entrypoint={meta.entrypoint}, mode={meta.mode}')
"`

Expected: All 6 recruiter coglets listed with correct entrypoints and modes.

**Step 5: Commit if any fixups needed**

```bash
git add -A && git commit -m "fix(recruiter): address migration fixups"
```
