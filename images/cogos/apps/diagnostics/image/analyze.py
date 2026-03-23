# Diagnostic: image/analyze — test describe, analyze, extract_text via Gemini Vision
import base64

checks = []

# Minimal 2x2 red PNG
_TEST_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVQI12P4z8BQDwAEgAF/"
    "QualzQAAAABJRU5ErkJggg=="
)

# Upload test image
test_key = None
try:
    ref = blob.upload(_TEST_PNG, "_diag_analyze_test.png", content_type="image/png")
    if hasattr(ref, "error") and ref.error:
        raise Exception(str(ref.error))
    test_key = ref.key
except Exception as e:
    checks.append({"name": "upload_test_image", "status": "fail", "ms": 0, "error": str(e)})

# describe
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.describe(test_key)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    if not hasattr(r, "description") or not r.description:
        raise Exception("empty description")
    checks.append({"name": "describe", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "describe", "status": "fail", "ms": 0, "error": str(e)[:200]})

# analyze
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.analyze(test_key, "What color is this image?")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    if not hasattr(r, "answer") or not r.answer:
        raise Exception("empty answer")
    checks.append({"name": "analyze", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "analyze", "status": "fail", "ms": 0, "error": str(e)[:200]})

# extract_text
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.extract_text(test_key)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    # Even if no text found, as long as no error it's fine
    checks.append({"name": "extract_text", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "extract_text", "status": "fail", "ms": 0, "error": str(e)[:200]})

print(json.dumps(checks))
