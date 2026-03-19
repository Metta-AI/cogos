@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/files.md}
@{mnt/boot/cogos/includes/memory/knowledge.md}

# Diagnostic: includes/memory/knowledge

Exercise the Knowledge memory policy instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Bootstrap**: Check if `data/knowledge.md` exists. If not, create it with the standard template (header + topic sections).

2. **Read knowledge**: Read `data/knowledge.md` and print its contents.

3. **Add a fact**: Add a new entry under `## Facts`: `"Diagnostic test: CogOS diagnostics ran successfully on this process."`. Follow the instructions — read first, check if it exists, then update.

4. **Read back**: Read `data/knowledge.md` again and print it to confirm the fact was added.

```python verify
doc = file.read("data/knowledge.md")
assert not hasattr(doc, "error"), "knowledge.md read error: " + str(getattr(doc, "error", ""))
assert "diagnostic" in doc.content.lower(), "diagnostic fact not found in knowledge.md"
```
