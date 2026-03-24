checks = []

try:
    if asana is None:
        checks.append({"name": "asana_wired", "status": "fail", "ms": 0, "error": "asana capability is None"})
    else:
        has_methods = len([m for m in dir(asana) if not m.startswith("_")]) > 0
        if has_methods:
            checks.append({"name": "asana_wired", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "asana_wired", "status": "fail", "ms": 0, "error": "no methods found on asana capability"})
except Exception as e:
    checks.append({"name": "asana_wired", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
