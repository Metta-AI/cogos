
checks = []

try:
    result = web_fetch.fetch("https://httpbin.org/get")
    ms = 0
    if result is None:
        checks.append({"name": "fetch_httpbin", "status": "fail", "ms": ms, "error": "returned None"})
    elif hasattr(result, "error") and result.error:
        checks.append({"name": "fetch_httpbin", "status": "fail", "ms": ms, "error": str(result.error)})
    elif hasattr(result, "content") and result.content:
        checks.append({"name": "fetch_httpbin", "status": "pass", "ms": ms})
    else:
        checks.append({"name": "fetch_httpbin", "status": "fail", "ms": ms, "error": "no content in response"})
except Exception as e:
    ms = 0
    checks.append({"name": "fetch_httpbin", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
