# Diagnostic: channels/spawn_channels — test create, send, read roundtrip
checks = []

try:
    channels.create("_diag:spawn:test")
    channels.send("_diag:spawn:test", {"seq": 1, "data": "first"})
    channels.send("_diag:spawn:test", {"seq": 2, "data": "second"})
    msgs = channels.read("_diag:spawn:test", limit=10)
    if not isinstance(msgs, list):
        raise Exception("read returned " + str(type(msgs)))
    if len(msgs) < 2:
        raise Exception("expected 2+ msgs, got " + str(len(msgs)))
    checks.append({"name": "send_read_roundtrip", "status": "pass", "ms": 0})
except Exception as e:
    checks.append({"name": "send_read_roundtrip", "status": "fail", "ms": 0, "error": str(e)})

print(json.dumps(checks))
