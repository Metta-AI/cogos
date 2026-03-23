# Diagnostic: image/compose — test overlay_text and combine
import base64

checks = []

# Minimal 2x2 red PNG
_TEST_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVQI12P4z8BQDwAEgAF/"
    "QualzQAAAABJRU5ErkJggg=="
)

# Upload test images
test_key = None
test_key2 = None
try:
    ref = blob.upload(_TEST_PNG, "_diag_compose_1.png", content_type="image/png")
    if hasattr(ref, "error") and ref.error:
        raise Exception(str(ref.error))
    test_key = ref.key
    ref2 = blob.upload(_TEST_PNG, "_diag_compose_2.png", content_type="image/png")
    if hasattr(ref2, "error") and ref2.error:
        raise Exception(str(ref2.error))
    test_key2 = ref2.key
except Exception as e:
    checks.append({"name": "upload_test_images", "status": "fail", "ms": 0, "error": str(e)})

# overlay_text
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.overlay_text(test_key, text="hi", position="center", font_size=10, color="white")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "overlay_text", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "overlay_text", "status": "fail", "ms": 0, "error": str(e)[:200]})

# combine
try:
    if test_key is None or test_key2 is None:
        raise Exception("skipped — no test images")
    r = image.combine([test_key, test_key2], layout="horizontal")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "combine", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "combine", "status": "fail", "ms": 0, "error": str(e)[:200]})

print(json.dumps(checks))
