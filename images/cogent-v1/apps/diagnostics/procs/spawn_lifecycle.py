# Diagnostic: procs/spawn_lifecycle — test list, get, spawn (no wait)
checks = []

# Test: procs.list()
try:
    proc_list = procs.list()
    if not isinstance(proc_list, list):
        raise Exception("list returned " + str(type(proc_list)))
    checks.append({"name": "list", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "list", "status": "fail", "ms": 0, "error": str(e)})

# Test: procs.spawn() returns handle (not error)
try:
    handle = procs.spawn("_diag/lifecycle/test", content='print("ok")', executor="python", mode="one_shot", capabilities={})
    if hasattr(handle, "error"):
        raise Exception(str(handle.error))
    checks.append({"name": "spawn", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "spawn", "status": "fail", "ms": 0, "error": str(e)})

# Test: procs.get()
try:
    h = procs.get(name="_diag/lifecycle/test")
    if hasattr(h, "error"):
        raise Exception(str(h.error))
    checks.append({"name": "get", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "get", "status": "fail", "ms": 0, "error": str(e)})

print(json.dumps(checks))
