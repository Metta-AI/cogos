# Diagnostic: procs/capability_scoping.py
# Tests scope narrowing — spawn child with scoped dir capability.
# Verifies child can access scoped dir but parent sees full scope.

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

# Child that writes a file using its scoped data capability
WRITER_CHILD = """
f = data.get("output.txt")
f.write("written by scoped child")
print("child wrote output.txt")
"""

# Child that tries to list files in its scoped data
LISTER_CHILD = """
entries = data.list()
keys = [e.key for e in entries]
print(json.dumps({"keys": keys, "count": len(keys)}))
"""

# Child that reads a specific file
READER_CHILD = """
f = data.get("input.txt")
r = f.read()
if hasattr(r, "error"):
    print(json.dumps({"error": str(r.error)}))
else:
    print(json.dumps({"content": r.content}))
"""

# ── Tests ────────────────────────────────────────────────────

def test_spawn_with_data_cap():
    """Spawn child with data capability and verify it can write."""
    handle = procs.spawn(
        "_diag/scope_writer",
        content=WRITER_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={"data": data},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    status = handle.status()
    assert status == "completed", "child did not complete: " + str(status)
    # Verify file was written
    f = data.get("output.txt")
    r = f.read()
    assert not hasattr(r, "error"), "could not read child output: " + str(getattr(r, "error", ""))
    assert r.content == "written by scoped child", "unexpected content: " + repr(r.content)

def test_child_can_list():
    """Spawn child that lists files in its scoped data."""
    # First create a file the child should see
    data.get("_diag/scope_list_test.txt").write("visible")
    handle = procs.spawn(
        "_diag/scope_lister",
        content=LISTER_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={"data": data},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    out = handle.stdout(limit=1)
    assert out is not None, "no stdout from lister child"
    parsed = json.loads(str(out))
    assert parsed["count"] > 0, "child listed 0 files"

def test_child_reads_parent_file():
    """Parent writes a file, child reads it via scoped capability."""
    data.get("input.txt").write("hello from parent")
    handle = procs.spawn(
        "_diag/scope_reader",
        content=READER_CHILD,
        executor="python",
        mode="one_shot",
        capabilities={"data": data},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    out = handle.stdout(limit=1)
    assert out is not None, "no stdout from reader child"
    parsed = json.loads(str(out))
    assert "error" not in parsed, "child got error: " + str(parsed.get("error"))
    assert parsed["content"] == "hello from parent", "content mismatch: " + repr(parsed["content"])

def test_no_caps_child():
    """Spawn child with empty capabilities — should still run."""
    handle = procs.spawn(
        "_diag/scope_nocaps",
        content='print("no caps child ok")',
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    status = handle.status()
    assert status == "completed", "no-caps child failed: " + str(status)
    out = handle.stdout(limit=1)
    assert out is not None and "no caps child ok" in str(out), "unexpected output"

def test_channels_cap_scoping():
    """Spawn child with only channels capability."""
    child_code = """
channels.create("_diag:scope_ch_test")
channels.send("_diag:scope_ch_test", {"from": "scoped_child"})
msgs = channels.read("_diag:scope_ch_test", limit=5)
print(json.dumps({"count": len(msgs)}))
"""
    handle = procs.spawn(
        "_diag/scope_channels",
        content=child_code,
        executor="python",
        mode="one_shot",
        capabilities={"channels": channels},
    )
    assert not hasattr(handle, "error"), "spawn error: " + str(getattr(handle, "error", ""))
    handle.wait()
    status = handle.status()
    assert status == "completed", "channels child failed: " + str(status)

# ── Run ──────────────────────────────────────────────────────

check("spawn_with_data_cap", test_spawn_with_data_cap)
check("child_can_list", test_child_can_list)
check("child_reads_parent_file", test_child_reads_parent_file)
check("no_caps_child", test_no_caps_child)
check("channels_cap_scoping", test_channels_cap_scoping)

print(json.dumps(results))
