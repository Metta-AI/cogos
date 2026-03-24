checks = []

try:
    if history is None:
        checks.append({"name": "history_wired", "status": "fail", "ms": 0, "error": "history capability is None"})
    else:
        has_methods = len([m for m in dir(history) if not m.startswith("_")]) > 0
        if has_methods:
            checks.append({"name": "history_wired", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "history_wired", "status": "fail", "ms": 0, "error": "no methods found on history capability"})
except Exception as e:
    checks.append({"name": "history_wired", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
