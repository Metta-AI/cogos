# Diagnostic: blob/upload_download — upload and download a blob
checks = []
test_key = "_diag_test_blob"
test_content = "diagnostics-verification"

try:
    result = blob.upload(test_key, test_content)
    if hasattr(result, "error") and result.error:
        raise Exception(str(result.error))
    checks.append({"name": "upload", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "upload", "status": "fail", "ms": 0, "error": str(e)})

try:
    result = blob.download(test_key)
    if hasattr(result, "error") and result.error:
        raise Exception(str(result.error))
    content = result.content if hasattr(result, "content") else str(result)
    if test_content not in content:
        raise Exception("content mismatch: " + repr(content)[:100])
    checks.append({"name": "download", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "download", "status": "fail", "ms": 0, "error": str(e)})

print(json.dumps(checks))
