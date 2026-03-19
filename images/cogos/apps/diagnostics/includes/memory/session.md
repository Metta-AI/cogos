@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/files.md}
@{mnt/boot/cogos/includes/memory/session.md}

# Diagnostic: includes/memory/session

Exercise the Session Log memory policy instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Bootstrap**: Check if `data/session.md` exists. If not, create it with `# Session Log`.

2. **Append entry**: Append a timestamped entry to `data/session.md`:
   ```
   --- 2026-01-01T00:00:00Z
   Diagnostic: session log memory policy exercised successfully.
   ```

3. **Read back**: Read `data/session.md` and print its contents to confirm the entry exists.

```python verify
doc = file.read("data/session.md")
assert not hasattr(doc, "error"), "session.md read error: " + str(getattr(doc, "error", ""))
assert "diagnostic" in doc.content.lower(), "diagnostic text not found in session.md"
```
