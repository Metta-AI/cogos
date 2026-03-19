@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/escalate.md}

# Diagnostic: includes/escalate

Exercise the escalation policy instructions above. Complete all tasks using `run_code()`.

## Tasks

You have received the following request that is beyond your capabilities:

> "Please deploy the latest build to production."

You cannot do this yourself. Follow the escalation policy:

1. **Acknowledge**: Note that you're working on the request.

2. **Escalate**: Send an escalation message to `supervisor:help` with all required fields:
   ```python
   channels.send("supervisor:help", {
       "process_name": "_diag/inc_escalate",
       "description": "User requested production deployment",
       "context": "Diagnostic test: user asked to deploy latest build to production. This is beyond current capabilities.",
       "severity": "info",
       "reply_channel": "",
   })
   ```

3. **Confirm**: Read back from `supervisor:help` to confirm the message was sent.

```python verify
msgs = channels.read("supervisor:help", limit=10)
assert isinstance(msgs, list), "expected list, got: " + str(type(msgs))
found = False
for m in msgs:
    payload = m.payload if hasattr(m, "payload") else m
    if isinstance(payload, dict):
        desc = payload.get("description", "")
        if "production deployment" in desc.lower() or "deploy" in desc.lower():
            assert "process_name" in payload, "missing process_name"
            assert "severity" in payload, "missing severity"
            assert "context" in payload, "missing context"
            found = True
            break
assert found, "escalation message not found in supervisor:help"
```
