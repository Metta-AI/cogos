@{cogos/includes/code_mode.md}
@{cogos/includes/files.md}

# Diagnostic: includes/files

Exercise the Files API instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Write a file**: Use `dir.get("_diag/inc_files_test.txt").write("hello diagnostic")` to create a test file.

2. **Read with head**: Use `dir.get("_diag/inc_files_test.txt").head(n=1)` and print the result.

3. **Edit**: Use `dir.get("_diag/inc_files_test.txt").edit(old="hello", new="greetings")` to replace text.

4. **Grep**: Use `dir.grep("greetings", prefix="_diag/")` and print matching keys.

5. **Glob**: Use `dir.glob("_diag/*.txt")` and print the file list.

6. **Tree**: Use `dir.tree(depth=2)` and print the output.

7. **Append**: Use `dir.get("_diag/inc_files_test.txt").append("\nappended line")`.

8. **Write results JSON**: Write a JSON summary to `_diag/inc_files_results.json` with keys: `wrote`, `read`, `edited`, `grepped`, `globbed`, `treed`, `appended` — each set to `true`.

```python verify
# Check edited content
doc = file.read("_diag/inc_files_test.txt")
assert not hasattr(doc, "error"), "read error: " + str(getattr(doc, "error", ""))
assert "greetings" in doc.content, "edit not applied: " + repr(doc.content)
assert "appended line" in doc.content, "append missing: " + repr(doc.content)

# Check results JSON
results = file.read("_diag/inc_files_results.json")
assert not hasattr(results, "error"), "results.json read error: " + str(getattr(results, "error", ""))
parsed = json.loads(results.content)
for key in ["wrote", "read", "edited", "grepped", "globbed", "treed", "appended"]:
    assert key in parsed, "missing key: " + key
    assert parsed[key] == True, key + " is not true"
```
