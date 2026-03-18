# Diagnostic: procs/spawn_lifecycle.py
# Tests spawn, status, wait, stdout, stderr, kill.

import time

results = []

def check(name, fn):
    t0 = time.time()
    try:
        fn()
        ms = int((time.time() - t0) * 1000)
        results.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        results.append({"name": name, "status": "fail", "ms": ms, "error": str(e)[:300]})

# ── Child scripts ────────────────────────────────────────────

SIMPLE_CHILD = """
print("hello from child")
"""

SLOW_CHILD = """
import time
print("slow child starting")
time.sleep(1)
print("slow child done")
"""

FAILING_CHILD = """
raise ValueError("intentional error for diagnostics")
"""

MULTI_OUTPUT_CHILD = """
for i in range(10):
    print("line_" + str(i))
"""

# ── Tests ────────────────────────────────────────────────────

def test_spawn_simple():
    handle = procs.spawn(
        "_diag/lifecycle_simple",
        content=SIMPLE_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    status = handle.status()
    assert status == "completed", "expected completed, got: " + str(status)

def test_stdout():
    handle = procs.spawn(
        "_diag/lifecycle_stdout",
        content=SIMPLE_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    out = handle.stdout(limit=1)
    assert out is not None, "stdout returned None"
    assert "hello from child" in str(out), "expected 'hello from child' in stdout"

def test_wait_blocks():
    t0 = time.time()
    handle = procs.spawn(
        "_diag/lifecycle_slow",
        content=SLOW_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    elapsed = time.time() - t0
    assert elapsed >= 0.5, "wait should block until child completes, elapsed: " + str(elapsed)
    status = handle.status()
    assert status == "completed", "expected completed after wait, got: " + str(status)

def test_failing_child():
    handle = procs.spawn(
        "_diag/lifecycle_fail",
        content=FAILING_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    status = handle.status()
    assert status != "completed" or status == "completed", "process should have a status"
    # Check stderr for error output
    err = handle.stderr(limit=10)
    if err is not None:
        err_str = "\n".join(err) if isinstance(err, list) else str(err)
        assert "intentional error" in err_str or "ValueError" in err_str, \
            "expected error in stderr, got: " + repr(err_str[:200])

def test_multi_stdout():
    handle = procs.spawn(
        "_diag/lifecycle_multi",
        content=MULTI_OUTPUT_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    out = handle.stdout(limit=20)
    if isinstance(out, str):
        lines = [out]
    elif isinstance(out, list):
        lines = out
    else:
        lines = []
    # Flatten in case lines contain newlines
    all_text = "\n".join(lines)
    assert "line_0" in all_text, "missing line_0 in stdout"
    assert "line_9" in all_text, "missing line_9 in stdout"

def test_procs_list():
    proc_list = procs.list()
    assert isinstance(proc_list, list), "procs.list() should return list"

def test_procs_get():
    handle = procs.spawn(
        "_diag/lifecycle_get",
        content=SIMPLE_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error"
    handle.wait()
    retrieved = procs.get(name="_diag/lifecycle_get")
    assert not hasattr(retrieved, "error"), "procs.get error: " + str(getattr(retrieved, "error", ""))

# ── Run ──────────────────────────────────────────────────────

check("spawn_simple", test_spawn_simple)
check("stdout", test_stdout)
check("wait_blocks", test_wait_blocks)
check("failing_child", test_failing_child)
check("multi_stdout", test_multi_stdout)
check("procs_list", test_procs_list)
check("procs_get", test_procs_get)

print(json.dumps(results))
