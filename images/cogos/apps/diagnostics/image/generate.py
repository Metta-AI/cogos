# Diagnostic: image/generate — test image generation via Gemini
checks = []

# generate
try:
    r = image.generate("a small red circle on white background", size="256x256")
    if hasattr(r, "error") and r.error:
        raise Exception(r.error)
    if not hasattr(r, "key") or not r.key:
        raise Exception("no key in result")
    checks.append({"name": "generate", "status": "pass", "ms": 0})

    # Use the generated image to test edit
    gen_key = r.key
    try:
        r2 = image.edit(gen_key, "add a blue border around the image")
        if hasattr(r2, "error") and r2.error:
            raise Exception(r2.error)
        if not hasattr(r2, "key") or not r2.key:
            raise Exception("no key in result")
        checks.append({"name": "edit", "status": "pass", "ms": 0})
    except Exception as e:
        checks.append({"name": "edit", "status": "fail", "ms": 0, "error": str(e)[:200]})

except Exception as e:
    checks.append({"name": "generate", "status": "fail", "ms": 0, "error": str(e)[:200]})
    checks.append({"name": "edit", "status": "fail", "ms": 0, "error": "skipped — generate failed"})

print(json.dumps(checks))
