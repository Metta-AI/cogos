@{cogos/includes/code_mode.md}
@{cogos/includes/channels.md}

# Diagnostic: includes/channels

Exercise the Channels API instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Create a channel**: Create a channel named `_diag/inc_ch_test` with schema `{"msg": "string", "seq": "number"}`.

2. **Send messages**: Send two messages to `_diag/inc_ch_test`:
   - `{"msg": "first", "seq": 1}`
   - `{"msg": "second", "seq": 2}`

3. **Read messages**: Read from `_diag/inc_ch_test` with `limit=10` and print the payloads.

4. **List channels**: Use `channels.list()` and print the result to confirm `_diag/inc_ch_test` appears.

```python verify
msgs = channels.read("_diag/inc_ch_test", limit=10)
assert isinstance(msgs, list), "expected list, got: " + str(type(msgs))
assert len(msgs) >= 2, "expected at least 2 messages, got: " + str(len(msgs))
payloads = [m.payload if hasattr(m, "payload") else m for m in msgs]
texts = [p.get("msg") if isinstance(p, dict) else str(p) for p in payloads]
assert "first" in texts, "missing 'first' message in: " + str(texts)
assert "second" in texts, "missing 'second' message in: " + str(texts)
```
