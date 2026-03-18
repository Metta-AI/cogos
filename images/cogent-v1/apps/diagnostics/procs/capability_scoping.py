# Diagnostic: procs/capability_scoping — verify procs + spawn with scoped caps
checks = []

# Test: spawn with scoped data capability
try:
    handle = procs.spawn(
        "_diag/scope/writer",
        content='data.get("scope_test.txt").write("scoped")\nprint("ok")',
        executor="python", mode="one_shot",
        capabilities={"data": data, "me": me, "stdlib": stdlib},
    )
    if hasattr(handle, "error"):
        raise Exception(str(handle.error))
    checks.append({"name": "spawn_with_caps", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "spawn_with_caps", "status": "fail", "ms": 0, "error": str(e)})

# Test: spawn with no capabilities
try:
    handle = procs.spawn(
        "_diag/scope/nocaps",
        content='print("nocaps ok")',
        executor="python", mode="one_shot", capabilities={},
    )
    if hasattr(handle, "error"):
        raise Exception(str(handle.error))
    checks.append({"name": "spawn_no_caps", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "spawn_no_caps", "status": "fail", "ms": 0, "error": str(e)})

print(json.dumps(checks))
