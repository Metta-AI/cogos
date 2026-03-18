import time

checks = []

t0 = time.time()
try:
    if alerts is None:
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": "alerts_wired", "status": "fail", "ms": ms, "error": "alerts capability is None"})
    else:
        has_methods = len([m for m in dir(alerts) if not m.startswith("_")]) > 0
        ms = int((time.time() - t0) * 1000)
        if has_methods:
            checks.append({"name": "alerts_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "alerts_wired", "status": "fail", "ms": ms, "error": "no methods found on alerts capability"})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "alerts_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
