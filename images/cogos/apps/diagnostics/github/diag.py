checks = []

try:
    if github is None:
        checks.append({"name": "github_wired", "status": "fail", "ms": 0, "error": "github capability is None"})
    else:
        has_methods = len([m for m in dir(github) if not m.startswith("_")]) > 0
        if has_methods:
            checks.append({"name": "github_wired", "status": "pass", "ms": 0})
        else:
            checks.append({"name": "github_wired", "status": "fail", "ms": 0, "error": "no methods found on github capability"})
except Exception as e:
    checks.append({"name": "github_wired", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
