# Diagnostic: scheduler/handler_wakeup — channel create, send, read
checks = []
try:
    channels.create("_diag:wakeup:test")
    channels.send("_diag:wakeup:test", {"type": "wakeup"})
    msgs = channels.read("_diag:wakeup:test", limit=5)
    found = False
    for m in (msgs if isinstance(msgs, list) else []):
        if isinstance(m, dict) and m.get("type") == "wakeup":
            found = True
    if not found:
        raise Exception("wakeup message not found")
    checks.append({"name": "channel_wakeup", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "channel_wakeup", "status": "fail", "ms": 0, "error": str(e)})
print(json.dumps(checks))
