# Diagnostic: LLM Messaging

You are running a diagnostic check for the CogOS channels system. Perform each step in order.

## Steps

1. **Create a channel** named `_diag:llm_msg_test` using `channels.create()`.

2. **Send a message** to the channel with payload:
   ```json
   {"from": "llm", "content": "diagnostic message", "step": 1}
   ```

3. **Send a second message** with payload:
   ```json
   {"from": "llm", "content": "follow up", "step": 2}
   ```

4. **Read messages** from the channel with `channels.read("_diag:llm_msg_test", limit=10)` and confirm you see both messages.

5. **List channels** using `channels.list()` and confirm `_diag:llm_msg_test` appears in the list.

Print "ALL STEPS COMPLETE" when finished.

```python verify
results = []
import time

def check(name, fn):
    t0 = time.time()
    try:
        fn()
        ms = int((time.time() - t0) * 1000)
        results.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        results.append({"name": name, "status": "fail", "ms": ms, "error": str(e)[:300]})

def test_channel_has_messages():
    msgs = channels.read("_diag:llm_msg_test", limit=10)
    assert isinstance(msgs, list), "read should return list"
    assert len(msgs) >= 2, "expected at least 2 messages, got " + str(len(msgs))

def test_message_content():
    msgs = channels.read("_diag:llm_msg_test", limit=10)
    payloads = [m for m in msgs if isinstance(m, dict)]
    has_step1 = any(m.get("step") == 1 or m.get("payload", {}).get("step") == 1 for m in payloads)
    has_step2 = any(m.get("step") == 2 or m.get("payload", {}).get("step") == 2 for m in payloads)
    assert has_step1, "missing message with step=1"
    assert has_step2, "missing message with step=2"

def test_channel_in_list():
    ch_list = channels.list()
    names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in ch_list]
    found = [n for n in names if "_diag:llm_msg_test" in n]
    assert len(found) >= 1, "channel not found in list"

check("channel_has_messages", test_channel_has_messages)
check("message_content", test_message_content)
check("channel_in_list", test_channel_in_list)

print(json.dumps(results))
```
