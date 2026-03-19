# Diagnostic: scheduler/dispatch — channels create/send/read
checks = []
try:
    channels.create("_diag:sched:test")
    channels.send("_diag:sched:test", {"seq": 1})
    msgs = channels.read("_diag:sched:test", limit=5)
    if not isinstance(msgs, list):
        raise Exception("read returned " + str(type(msgs)))
    checks.append({"name": "channel_roundtrip", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "channel_roundtrip", "status": "fail", "ms": 0, "error": str(e)})
print(json.dumps(checks))
