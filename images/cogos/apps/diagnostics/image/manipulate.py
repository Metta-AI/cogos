# Diagnostic: image/manipulate — test resize, crop, rotate, thumbnail, convert
import base64

checks = []

# Minimal 2x2 red PNG (valid PNG file)
_TEST_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVQI12P4z8BQDwAEgAF/"
    "QualzQAAAABJRU5ErkJggg=="
)

# Upload a test image via blob
test_key = None
try:
    ref = blob.upload(_TEST_PNG, "_diag_image_test.png", content_type="image/png")
    if hasattr(ref, "error") and ref.error:
        raise Exception(str(ref.error))
    test_key = ref.key
    checks.append({"name": "upload_test_image", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "upload_test_image", "status": "fail", "ms": 0, "error": str(e)})

# resize
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.resize(test_key, width=4)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "resize", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "resize", "status": "fail", "ms": 0, "error": str(e)[:200]})

# crop
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.crop(test_key, left=0, top=0, right=1, bottom=1)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "crop", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "crop", "status": "fail", "ms": 0, "error": str(e)[:200]})

# rotate
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.rotate(test_key, degrees=90)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "rotate", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "rotate", "status": "fail", "ms": 0, "error": str(e)[:200]})

# thumbnail
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.thumbnail(test_key, max_size=1)
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "thumbnail", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "thumbnail", "status": "fail", "ms": 0, "error": str(e)[:200]})

# convert
try:
    if test_key is None:
        raise Exception("skipped — no test image")
    r = image.convert(test_key, format="JPEG")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    checks.append({"name": "convert", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "convert", "status": "fail", "ms": 0, "error": str(e)[:200]})

print(json.dumps(checks))
