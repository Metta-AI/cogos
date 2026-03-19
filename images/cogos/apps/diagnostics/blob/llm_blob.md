# Blob Store Diagnostic

You have access to the `blob` capability. Perform the following checks:

1. Call `blob.upload("_diag_llm_test", "hello from diagnostics")` to store a small value.
2. Call `blob.download("_diag_llm_test")` to retrieve it.
3. Verify the downloaded content matches what was uploaded.

Report what you found. If any call fails, describe the error.

```python verify
import time

checks = []
test_key = "_diag_llm_verify"
test_content = "verify-blob-" + str(int(time.time()))

t0 = time.time()
try:
    blob.upload(test_key, test_content)
    result = blob.download(test_key)
    ms = int((time.time() - t0) * 1000)
    content = result.content if hasattr(result, "content") else str(result)
    if content == test_content:
        checks.append({"name": "llm_blob_verify", "status": "pass", "ms": ms})
    else:
        checks.append({"name": "llm_blob_verify", "status": "fail", "ms": ms, "error": "content mismatch"})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "llm_blob_verify", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
```
