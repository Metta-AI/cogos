# Web Fetch Diagnostic

You have access to the `web_fetch` capability. Perform the following check:

1. Call `web_fetch.fetch("https://httpbin.org/get")`.
2. Report the result. If successful, confirm you received JSON content with request headers.
3. Do NOT fetch any other URLs.

Report what you found. If the call fails, describe the error.

```python verify
import time

checks = []

t0 = time.time()
try:
    result = web_fetch.fetch("https://httpbin.org/get")
    ms = int((time.time() - t0) * 1000)
    if result is None:
        checks.append({"name": "llm_web_fetch_verify", "status": "fail", "ms": ms, "error": "returned None"})
    elif hasattr(result, "error") and result.error:
        checks.append({"name": "llm_web_fetch_verify", "status": "fail", "ms": ms, "error": str(result.error)})
    elif hasattr(result, "content") and result.content:
        checks.append({"name": "llm_web_fetch_verify", "status": "pass", "ms": ms})
    else:
        checks.append({"name": "llm_web_fetch_verify", "status": "fail", "ms": ms, "error": "no content"})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "llm_web_fetch_verify", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
```
