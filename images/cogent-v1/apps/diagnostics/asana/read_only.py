
checks = []

try:
    if asana is None:
        ms = int((0 - t0) * 1000)
        checks.append({"name": "asana_wired", "status": "fail", "ms": ms, "error": "asana capability is None"})
    else:
        has_methods = len([m for m in dir(asana) if not m.startswith("_")]) > 0
        ms = int((0 - t0) * 1000)
        if has_methods:
            checks.append({"name": "asana_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "asana_wired", "status": "fail", "ms": ms, "error": "no methods found on asana capability"})
except Exception as e:
    ms = int((0 - t0) * 1000)
    checks.append({"name": "asana_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
