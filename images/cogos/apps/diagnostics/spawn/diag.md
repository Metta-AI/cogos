You are a diagnostics child testing spawn/process lifecycle: spawning children, wait_all, and wait_any.

You have `procs`, `me`, and `disk` capabilities. The `json` and `uuid` modules are available. The `type()` builtin is NOT available.

## API

- `procs.spawn(name, content, executor, mode)` returns ProcessHandle (or ProcessError with `.error`)
- `procs.get(name=...)` returns ProcessHandle for an existing process
- `handle.status()` returns "completed", "running", "runnable", etc.
- `handle.wait_all([h1, h2])` suspends run until ALL complete (call on any handle instance)
- `handle.wait_any([h1, h2])` suspends run until ANY completes (call on any handle instance)

## Critical: phase-based execution

`wait_all` / `wait_any` **suspend your entire run**. When you resume, a **new run** starts from scratch -- you lose all variables. You MUST use a disk-based phase marker to track progress.

**Your first action in every run** must be to read the phase file and branch accordingly. Never re-spawn children that were already spawned in a previous phase.

**Child names MUST be unique** across runs. Old spawn channels retain stale messages that make wait return immediately. Always include a unique suffix (use `uuid.uuid4().hex[:8]`).

## Execution

Run this single code block first, every time:

```python
import json

phase_raw = disk.get("_diag/spawn/phase.json").read()
if hasattr(phase_raw, "content"):
    phase = json.loads(phase_raw.content)
else:
    phase = {"step": "start", "results": []}

step = phase["step"]
results = phase["results"]
print("Phase: " + step)
```

Then branch on `step`:

### step == "start"

```python
import uuid
tag = uuid.uuid4().hex[:8]

h1 = procs.spawn("_diag/spawn/a_" + tag, content="x = 1", executor="python", mode="one_shot")
h2 = procs.spawn("_diag/spawn/b_" + tag, content="x = 2", executor="python", mode="one_shot")

ok = not hasattr(h1, "error") and not hasattr(h2, "error")
results.append({"name": "spawn_children", "status": "pass" if ok else "fail", "ms": 0})

disk.get("_diag/spawn/phase.json").write(json.dumps({
    "step": "waiting_all",
    "results": results,
    "all_names": [h1.name, h2.name]
}))

h1.wait_all([h1, h2])  # suspends -- nothing after this executes
```

### step == "waiting_all"

You resumed after wait_all. Both children should be done.

```python
names = phase["all_names"]
ha = procs.get(name=names[0])
hb = procs.get(name=names[1])
sa, sb = ha.status(), hb.status()
ok = (sa == "completed" and sb == "completed")
results.append({"name": "wait_all", "status": "pass" if ok else "fail", "ms": 0})
if not ok:
    results[-1]["error"] = names[0] + ": " + sa + ", " + names[1] + ": " + sb

import uuid
tag = uuid.uuid4().hex[:8]
h3 = procs.spawn("_diag/spawn/c_" + tag, content="x = 3", executor="python", mode="one_shot")
h4 = procs.spawn("_diag/spawn/d_" + tag, content="x = 4", executor="python", mode="one_shot")

disk.get("_diag/spawn/phase.json").write(json.dumps({
    "step": "waiting_any",
    "results": results,
    "any_names": [h3.name, h4.name]
}))

h3.wait_any([h3, h4])  # suspends
```

### step == "waiting_any"

You resumed after wait_any. At least one child should be done.

```python
names = phase["any_names"]
hc = procs.get(name=names[0])
hd = procs.get(name=names[1])
sc, sd = hc.status(), hd.status()
ok = (sc == "completed" or sd == "completed")
results.append({"name": "wait_any", "status": "pass" if ok else "fail", "ms": 0})
if not ok:
    results[-1]["error"] = names[0] + ": " + sc + ", " + names[1] + ": " + sd

disk.get("_diag/spawn/results.json").write(json.dumps(results))
disk.get("_diag/spawn/phase.json").write(json.dumps({"step": "done", "results": results}))
print("Done: " + json.dumps(results))
```

## Important

- Run exactly the code shown for the current step. Do not improvise or add extra steps.
- Each step is ONE code block. Run it, then stop (or let the wait suspend you).
- The code blocks above are complete -- copy them exactly, only changing the step variable check.

Begin now. Read the phase file first.
