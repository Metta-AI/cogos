
checks = []

try:
    if github is None:
        ms = 0
        checks.append({"name": "github_wired", "status": "fail", "ms": ms, "error": "github capability is None"})
    else:
        has_methods = len([m for m in dir(github) if not m.startswith("_")]) > 0
        ms = 0
        if has_methods:
            checks.append({"name": "github_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "github_wired", "status": "fail", "ms": ms, "error": "no methods found on github capability"})
except Exception as e:
    ms = 0
    checks.append({"name": "github_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
