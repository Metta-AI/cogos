# Image Capability Diagnostic

You have access to the `image` capability. Perform the following checks:

1. Verify the `image` capability is available (not None).
2. Check that all expected methods exist: resize, crop, rotate, convert, thumbnail, overlay_text, watermark, combine, describe, analyze, extract_text, generate, edit, variations.
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
        expected = [
            "resize", "crop", "rotate", "convert", "thumbnail",
            "overlay_text", "watermark", "combine",
            "describe", "analyze", "extract_text",
            "generate", "edit", "variations",
        ]
        missing = [m for m in expected if not hasattr(image, m)]
        ms = int((time.time() - t0) * 1000)
        if not missing:
            checks.append({"name": "llm_image_verify", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "llm_image_verify", "status": "fail", "ms": ms, "error": "missing: " + ", ".join(missing)})
except Exception as e:
    ms = int((time.time() - t0) * 1000)
    checks.append({"name": "llm_image_verify", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
```
