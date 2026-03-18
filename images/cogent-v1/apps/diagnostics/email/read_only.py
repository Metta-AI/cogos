import time

checks = []

t0 = time.time()
try:
    if email is None:
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": "email_wired", "status": "fail", "ms": ms, "error": "email capability is None"})
    else:
        # Verify the capability object exists and has methods
        has_methods = len([m for m in dir(email) if not m.startswith("_")]) > 0
        ms = int((time.time() - t0) * 1000)
        if has_methods:
            checks.append({"name": "email_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "email_wired", "status": "fail", "ms": ms, "error": "no methods found on email capability"})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "email_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
