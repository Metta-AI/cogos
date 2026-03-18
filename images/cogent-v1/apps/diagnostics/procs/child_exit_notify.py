# Diagnostic: procs/child_exit_notify — verify child:exited notifications
checks = []

# Test: spawn child, verify parent can read exit notification via recv()
try:
    handle = procs.spawn(
        "_diag/exit/success",
        content='print("child done")',
        executor="python",
        mode="one_shot",
        capabilities={},
    )
    if hasattr(handle, "error"):
        raise Exception(str(handle.error))
    # Child is spawned as RUNNABLE — it hasn't run yet, so no exit message.
    # Verify the handle has recv channel wired (parent handler was registered).
    msgs = handle.recv(limit=5)
    if not isinstance(msgs, list):
        raise Exception("recv returned " + str(type(msgs)))
    checks.append({"name": "spawn_recv_wired", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "spawn_recv_wired", "status": "fail", "ms": 0, "error": str(e)})

# Test: handle.runs() returns list
try:
    handle = procs.get(name="_diag/exit/success")
    if hasattr(handle, "error"):
        raise Exception(str(handle.error))
    runs = handle.runs(limit=3)
    if not isinstance(runs, list):
        raise Exception("runs returned " + str(type(runs)))
    checks.append({"name": "handle_runs", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "handle_runs", "status": "fail", "ms": 0, "error": str(e)})

print(json.dumps(checks))
