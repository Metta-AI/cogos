import base64

checks = []

_TEST_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVQI12P4z8BQDwAEgAF/"
    "QualzQAAAABJRU5ErkJggg=="
)

test_key = None
try:
    ref = blob.upload(_TEST_PNG, "_diag_image_test.png", content_type="image/png")
    if hasattr(ref, "error") and ref.error:
        raise Exception(str(ref.error))
    test_key = ref.key
    checks.append({"name": "upload_test_image", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "upload_test_image", "status": "fail", "ms": 0, "error": str(e)[:300]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.describe(test_key)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    if not hasattr(r, "description") or not r.description:
        raise Exception("empty description")
    checks.append({"name": "describe", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "describe", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.analyze(test_key, "What color is this image?")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    if not hasattr(r, "answer") or not r.answer:
        raise Exception("empty answer")
    checks.append({"name": "analyze", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "analyze", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.extract_text(test_key)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "extract_text", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "extract_text", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.resize(test_key, width=4)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "resize", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "resize", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.crop(test_key, left=0, top=0, right=1, bottom=1)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "crop", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "crop", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.rotate(test_key, degrees=90)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "rotate", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "rotate", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.thumbnail(test_key, max_size=1)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "thumbnail", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "thumbnail", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.convert(test_key, format="JPEG")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "convert", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "convert", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    if test_key is None:
        raise Exception("skipped -- no test image")
    r = image.overlay_text(test_key, text="hi", position="center", font_size=10, color="white")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "overlay_text", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "overlay_text", "status": "fail", "ms": 0, "error": str(e)[:200]})

try:
    r = image.generate("a small red circle on white background", size="256x256")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    if not hasattr(r, "key") or not r.key:
        raise Exception("no key in result")
    checks.append({"name": "generate", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "generate", "status": "fail", "ms": 0, "error": str(e)[:200]})

print(json.dumps(checks))
