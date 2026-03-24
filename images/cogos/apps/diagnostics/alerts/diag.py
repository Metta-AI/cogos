checks = []

try:
    if alerts is None:
        checks.append({"name": "alerts_wired", "status": "fail", "ms": 0, "error": "alerts capability is None"})
    else:
        has_methods = len([m for m in dir(alerts) if not m.startswith("_")]) > 0
        if has_methods:
            checks.append({"name": "alerts_wired", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "alerts_wired", "status": "fail", "ms": 0, "error": "no methods found on alerts capability"})
except Exception as e:
    checks.append({"name": "alerts_wired", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
