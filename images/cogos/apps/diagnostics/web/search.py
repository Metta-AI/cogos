
checks = []

try:
    result = web_search.search("test query diagnostics")
    ms = 0
    if result is None:
        checks.append({"name": "web_search", "status": "fail", "ms": ms, "error": "returned None"})
    elif hasattr(result, "error") and result.error:
        checks.append({"name": "web_search", "status": "fail", "ms": ms, "error": str(result.error)})
    else:
        checks.append({"name": "web_search", "status": "pass", "ms": ms})
except Exception as e:
    ms = 0
    checks.append({"name": "web_search", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
