@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/memory/ledger.md}

# Diagnostic: includes/memory/ledger

Exercise the Ledger memory policy instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Bootstrap**: Check if `data/ledger.jsonl` exists. If not, create it empty.

2. **Append entry 1**: Append a JSONL entry:
   ```json
   {"t": "2026-01-01T00:00:00Z", "type": "diagnostic", "summary": "ledger diagnostic started"}
   ```

3. **Append entry 2**: Append a second JSONL entry:
   ```json
   {"t": "2026-01-01T00:00:01Z", "type": "diagnostic", "summary": "ledger diagnostic completed"}
   ```

4. **Read back**: Read `data/ledger.jsonl` and print the last few lines to confirm both entries exist.

```python verify
doc = file.read("data/ledger.jsonl")
assert not hasattr(doc, "error"), "ledger.jsonl read error: " + str(getattr(doc, "error", ""))
lines = [l.strip() for l in doc.content.strip().split("\n") if l.strip()]
assert len(lines) >= 2, "expected at least 2 entries, got: " + str(len(lines))
last = json.loads(lines[-1])
assert last.get("type") == "diagnostic", "last entry type is not diagnostic: " + str(last)
```
