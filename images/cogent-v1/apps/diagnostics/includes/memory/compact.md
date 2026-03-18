@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}
@{cogos/includes/memory/compact.md}

# Diagnostic: includes/memory/compact

Exercise the Compact memory policy instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Bootstrap session.md**: Check if `data/session.md` exists. If not, create it with `# Session Log`.

2. **Bootstrap summary.md**: Check if `data/summary.md` exists. If not, create it with `# Summary`.

3. **Read both files**: Read `data/summary.md` and `data/session.md`, print their contents.

4. **Append entry**: Append a timestamped entry to `data/session.md`:
   ```
   --- 2026-01-01T00:00:00Z
   Diagnostic: compact memory policy exercised. Session and summary bootstrapped.
   ```

5. **Read back**: Read `data/session.md` and print to confirm the entry was appended.

```python verify
doc = file.read("data/session.md")
assert not hasattr(doc, "error"), "session.md read error: " + str(getattr(doc, "error", ""))
assert "diagnostic" in doc.content.lower(), "diagnostic text not found in session.md"
```
