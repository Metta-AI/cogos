
checks = []

# Check: verify image capability is wired and has expected methods
try:
    if image is None:
        ms = int((0 - t0) * 1000)
        checks.append({"name": "image_wired", "status": "fail", "ms": ms, "error": "image capability is None"})
    else:
        has_analyze = hasattr(image, "analyze")
        has_describe = hasattr(image, "describe")
        ms = int((0 - t0) * 1000)
        if has_analyze or has_describe:
            methods = []
            if has_analyze:
                methods.append("analyze")
            if has_describe:
                methods.append("describe")
            checks.append({"name": "image_wired", "status": "pass", "ms": ms})
        else:
            checks.append({"name": "image_wired", "status": "fail", "ms": ms, "error": "no analyze or describe method found"})
except Exception as e:
    ms = int((0 - t0) * 1000)
    checks.append({"name": "image_wired", "status": "fail", "ms": ms, "error": str(e)})

print(json.dumps(checks))
