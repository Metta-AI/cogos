
checks = []
test_key = "_diag_test_blob"
test_content = "diagnostics-verification-" + str(int(0))

# Check 1: upload
try:
    upload_result = blob.upload(test_key, test_content)
    ms = int((0 - t0) * 1000)
    if upload_result is None:
        checks.append({"name": "blob_upload", "status": "fail", "ms": ms, "error": "returned None"})
    elif hasattr(upload_result, "error") and upload_result.error:
        checks.append({"name": "blob_upload", "status": "fail", "ms": ms, "error": str(upload_result.error)})
    else:
        checks.append({"name": "blob_upload", "status": "pass", "ms": ms})
except Exception as e:
    ms = int((0 - t0) * 1000)
    checks.append({"name": "blob_upload", "status": "fail", "ms": ms, "error": str(e)})

# Check 2: download and verify match
try:
    download_result = blob.download(test_key)
    ms = int((0 - t0) * 1000)
    if download_result is None:
        checks.append({"name": "blob_download", "status": "fail", "ms": ms, "error": "returned None"})
    elif hasattr(download_result, "error") and download_result.error:
        checks.append({"name": "blob_download", "status": "fail", "ms": ms, "error": str(download_result.error)})
    else:
        content = download_result.content if hasattr(download_result, "content") else str(download_result)
        if content == test_content:
            checks.append({"name": "blob_download", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "blob_download", "status": "fail", "ms": ms, "error": "content mismatch"})
except Exception as e:
    ms = int((0 - t0) * 1000)
    checks.append({"name": "blob_download", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
