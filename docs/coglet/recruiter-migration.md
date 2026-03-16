# Recruiter → Coglets Migration Design

## Overview

Convert the recruiter system from file-based prompts/config into six coglets, each managed by the recruiter orchestrator as an Author. The orchestrator creates coglets, runs them as processes, and patches them via the `evolve` sub-process.

Every change to criteria, rubric, strategy, or prompts is tested before merge and versioned with optimistic concurrency.

## Coglets

| Coglet | Type | Files | Entrypoint |
|--------|------|-------|------------|
| `recruiter-config` | Data only | criteria.md, rubric.json, strategy.md, diagnosis.md, sourcer/*.md, evolution.md | None |
| `recruiter-discover` | Executable | main.md | main.md |
| `recruiter-present` | Executable | main.md | main.md |
| `recruiter-profile` | Executable | main.md | main.md |
| `recruiter-evolve` | Executable | main.md | main.md |
| `recruiter-orchestrator` | Executable | main.md | main.md |

All test commands use the python executor (`python tests/validate.py`) — no subprocess calls.

## CogletMeta Extension

`CogletMeta` gains new fields for runtime execution:

```python
class CogletMeta(BaseModel):
    # Existing
    id: str
    name: str
    test_command: str
    executor: str = "subprocess"
    timeout_seconds: int = 60
    version: int = 0
    patches: dict[str, PatchInfo] = {}

    # New — runtime execution
    entrypoint: str | None = None        # e.g. "main.md" — None means data-only coglet
    process_executor: str = "llm"        # "llm" or "python"
    model: str | None = None
    capabilities: list[str | dict] = []  # same format as image spec add_process()
    mode: str = "one_shot"               # "one_shot" or "daemon"
    idle_timeout_ms: int | None = None
```

## CogletCapability.run()

New method on `CogletCapability`:

```python
def run(
    self,
    procs: ProcsCapability,
    capability_overrides: dict[str, Any] | None = None,
    subscribe: str | None = None,
) -> ProcessHandle | CogletError:
```

When called:
1. Reads entrypoint file from main
2. Reads meta for process_executor, model, mode, capabilities
3. Calls `procs.spawn()` with content from entrypoint, capabilities merged from meta defaults + overrides

The orchestrator calls it like:
```python
handle = discover_coglet.run(procs, capability_overrides={"data": data})
```

Returns a standard ProcessHandle — after spawn, normal CogOS supervision applies.

## Structural Validation Tests

Each coglet contains a `tests/validate.py` that runs via `python tests/validate.py`. All validation is pure Python — no subprocess calls.

### Prompt coglets (discover, present, profile, evolve, orchestrator)

```python
import json, re, os, sys

content = open("main.md").read()
assert len(content) > 50, "entrypoint too short"
assert "## " in content, "missing markdown sections"

# Check inline Python code blocks parse
blocks = re.findall(r'```python\n(.*?)```', content, re.DOTALL)
for block in blocks:
    compile(block, "<prompt>", "exec")

print("PASS")
```

### Config coglet (recruiter-config)

```python
import json, os

# rubric.json parses with numeric values
rubric = json.load(open("rubric.json"))
assert all(isinstance(v, (int, float)) for v in rubric.values()), "rubric values must be numeric"

# criteria.md has required sections
criteria = open("criteria.md").read()
for section in ["## Must-Have", "## Strong Signals", "## Red Flags"]:
    assert section in criteria, f"criteria.md missing {section}"

# sourcer files exist and are non-empty
for name in ["github.md", "twitter.md", "web.md", "substack.md"]:
    path = f"sourcer/{name}"
    assert os.path.exists(path), f"missing {path}"
    assert len(open(path).read()) > 20, f"{path} too short"

# diagnosis.md exists
assert os.path.exists("diagnosis.md"), "missing diagnosis.md"
assert len(open("diagnosis.md").read()) > 20, "diagnosis.md too short"

# strategy.md exists
assert os.path.exists("strategy.md"), "missing strategy.md"

print("PASS")
```

## How Evolve Uses Coglets

The `evolve` process gets scoped `CogletCapability` instances for the coglets it can modify:

```python
handle = evolve_coglet.run(procs, capability_overrides={
    "config_coglet": coglet.scope(coglet_id=config_coglet_id),
    "discover_coglet": coglet.scope(coglet_id=discover_coglet_id),
    "present_coglet": coglet.scope(coglet_id=present_coglet_id),
    "profile_coglet": coglet.scope(coglet_id=profile_coglet_id),
    "data": data,
    "discord": discord,
    "secrets": secrets,
    "me": me,
})
```

Evolve's workflow:

1. **Diagnose** — read feedback from `data/feedback.jsonl`, classify gaps
2. **Read current state** — `config_coglet.read_file("criteria.md")`, etc.
3. **Propose patch** — `config_coglet.propose_patch(diff)` — tests run automatically
4. **Check result** — if `test_passed`, post approval request to Discord. If tests failed, adjust and re-propose.
5. **On approval** — `config_coglet.merge_patch(patch_id)`
6. **On rejection** — `config_coglet.discard_patch(patch_id)`

## Orchestrator Lifecycle

The recruiter orchestrator is itself a coglet. It's declared in the image init script and a process runs it.

**On first tick:**
1. Check if other coglets exist via `coglet_factory.list()`
2. Create any missing ones
3. Run them as needed via `coglet.run(procs, ...)`

**On subsequent ticks** (same as today):
1. Ensure `recruiter-present` is running
2. Check if discovery is needed — run discover coglet
3. Check feedback count — if enough, run evolve coglet
4. Log activity

The orchestrator holds `coglet_factory` (to create coglets) and `coglet` (scoped per coglet ID). It is the Author in the authoring protocol.

## Migration Path

### What moves into coglets

All files under `apps/recruiter/` become initial contents of the six coglets. The prompt files become `main.md` in their respective coglets.

### What stays

`data/recruiter/` is untouched — candidates, feedback, session/summary remain as regular files accessed via the `data` dir capability.

### What gets removed

`apps/recruiter/init/processes.py` and all prompt/config files under `apps/recruiter/`. They live in the coglet file store instead.

### Image init changes

Replace the current recruiter process definitions with coglet declarations:

```python
add_coglet(
    name="recruiter-orchestrator",
    test_command="python tests/validate.py",
    entrypoint="main.md",
    process_executor="llm",
    mode="daemon",
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "secrets", "stdlib", "coglet_factory", "coglet",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/recruiter/"}},
    ],
    files={
        "main.md": "...",           # current recruiter.md content
        "tests/validate.py": "...", # structural validation script
    },
)

add_coglet(
    name="recruiter-config",
    test_command="python tests/validate.py",
    files={
        "criteria.md": "...",
        "rubric.json": "...",
        "strategy.md": "...",
        "diagnosis.md": "...",
        "evolution.md": "",
        "sourcer/github.md": "...",
        "sourcer/twitter.md": "...",
        "sourcer/web.md": "...",
        "sourcer/substack.md": "...",
        "tests/validate.py": "...",
    },
)

# Similar for discover, present, profile, evolve coglets
```

## Implementation Order

1. Extend `CogletMeta` with runtime fields (entrypoint, process_executor, model, capabilities, mode)
2. Add `run()` to `CogletCapability`
3. Extend `add_coglet()` in image spec to accept runtime fields
4. Write validation scripts for each coglet type
5. Create the six coglet declarations in a new `apps/recruiter/init/coglets.py`
6. Update orchestrator prompt to use coglet capabilities instead of file references
7. Update evolve prompt to use propose_patch/merge_patch
8. Remove old process definitions and file-based prompts
9. Test full flow: reload, orchestrator tick, discovery, evolution
