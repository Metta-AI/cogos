checks = []

try:
    result = web_fetch.fetch("https://httpbin.org/get")
    if result is None:
        checks.append({"name": "fetch_httpbin", "status": "fail", "ms": 0, "error": "returned None"})
    elif hasattr(result, "error") and result.error:
        checks.append({"name": "fetch_httpbin", "status": "fail", "ms": 0, "error": str(result.error)[:300]})
    elif hasattr(result, "content") and result.content:
        checks.append({"name": "fetch_httpbin", "status": "pass", "ms": 0})
    else:
        checks.append({"name": "fetch_httpbin", "status": "fail", "ms": 0, "error": "no content in response"})
except Exception as e:
    checks.append({"name": "fetch_httpbin", "status": "fail", "ms": 0, "error": str(e)[:300]})

try:
    result = web_search.search("test query diagnostics")
    if result is None:
        checks.append({"name": "web_search", "status": "fail", "ms": 0, "error": "returned None"})
    elif hasattr(result, "error") and result.error:
        checks.append({"name": "web_search", "status": "fail", "ms": 0, "error": str(result.error)[:300]})
    else:
        checks.append({"name": "web_search", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "web_search", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
