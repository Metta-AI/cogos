# Image Capability Diagnostic

You have access to the `image` capability. Perform the following check:

1. Verify the `image` capability is available (not None).
2. Check what methods are available on it (e.g., `analyze`, `describe`).
3. Report the available methods. Do NOT call any methods that would process actual images.

Report what you found. If the capability is missing, describe the error.

```python verify
import time

checks = []

t0 = time.time()
try:
    if image is None:
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": "llm_image_verify", "status": "fail", "ms": ms, "error": "image is None"})
    else:
        has_analyze = hasattr(image, "analyze")
        has_describe = hasattr(image, "describe")
        ms = int((time.time() - t0) * 1000)
        if has_analyze or has_describe:
            checks.append({"name": "llm_image_verify", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "llm_image_verify", "status": "fail", "ms": ms, "error": "no expected methods"})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "llm_image_verify", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
```
