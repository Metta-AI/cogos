@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/files.md}
@{mnt/boot/cogos/includes/memory/scratchpad.md}

# Diagnostic: includes/memory/scratchpad

Exercise the Scratchpad memory policy instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Bootstrap**: Check if `data/scratchpad.md` exists. If not, create it with `# Scratchpad`.

2. **Write a plan**: Overwrite `data/scratchpad.md` with a diagnostic plan:
   ```
   # Scratchpad

   ## Current Plan
   - Step 1: Run diagnostic
   - Step 2: Verify results
   ```

3. **Overwrite with result**: Overwrite `data/scratchpad.md` with:
   ```
   # Scratchpad

   ## Result
   Diagnostic completed successfully.
   ```

4. **Clear**: Following the completion policy, clear the scratchpad back to just `# Scratchpad`.

5. **Confirm**: Read `data/scratchpad.md` and print its contents.

```python verify
doc = file.read("data/scratchpad.md")
assert not hasattr(doc, "error"), "scratchpad.md read error: " + str(getattr(doc, "error", ""))
content = doc.content.strip()
assert content == "# Scratchpad", "scratchpad not cleared, got: " + repr(content)
```
