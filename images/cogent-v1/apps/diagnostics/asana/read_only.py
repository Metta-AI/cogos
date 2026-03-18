
checks = []

try:
    if asana is None:
        ms = 0
        checks.append({"name": "asana_wired", "status": "fail", "ms": ms, "error": "asana capability is None"})
    else:
        has_methods = len([m for m in dir(asana) if not m.startswith("_")]) > 0
        ms = 0
        if has_methods:
            checks.append({"name": "asana_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "asana_wired", "status": "fail", "ms": ms, "error": "no methods found on asana capability"})
except Exception as e:
    ms = 0
    checks.append({"name": "asana_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
