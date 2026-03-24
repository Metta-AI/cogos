checks = []
test_key = "_diag_test_blob"
test_content = "diagnostics-verification"

blob_key = None
try:
    result = blob.upload(test_content, test_key)
    if hasattr(result, "error") and result.error:
        raise Exception(str(result.error))
    blob_key = result.key
    checks.append({"name": "upload", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "upload", "status": "fail", "ms": 0, "error": str(e)[:300]})

try:
    if blob_key is None:
        raise Exception("skipped -- upload failed")
    result = blob.download(blob_key)
    if hasattr(result, "error") and result.error:
        raise Exception(str(result.error))
    content = result.data if hasattr(result, "data") else str(result)
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    if test_content not in content:
        raise Exception("content mismatch: " + repr(content)[:100])
    checks.append({"name": "download", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "download", "status": "fail", "ms": 0, "error": str(e)[:300]})

print(json.dumps(checks))
