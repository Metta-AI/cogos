# Diagnostic: LLM File Operations

You are running a diagnostic check for the CogOS file system. Perform each step in order using the capabilities available to you.

## Steps

1. **Create a file** at `_diag/llm_file_test.txt` in the `data` directory with the content:
   ```
   diagnostic test line one
   diagnostic test line two
   ```

2. **Read the file** back from `_diag/llm_file_test.txt` and confirm it contains both lines.

3. **Edit the file** — replace `line one` with `line alpha` in `_diag/llm_file_test.txt`.

4. **Read the file again** and confirm the edit was applied (should contain `line alpha` and `line two`).

5. **Append** the text `diagnostic test line three\n` to the file.

6. **Read the file** one final time and confirm all three lines are present.

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

def test_file_exists():
    f = data.get("_diag/llm_file_test.txt")
    r = f.read()
    assert not hasattr(r, "error"), "file not found: " + str(getattr(r, "error", ""))

def test_edit_applied():
    f = data.get("_diag/llm_file_test.txt")
    r = f.read()
    assert "line alpha" in r.content, "edit not applied: missing 'line alpha'"
    assert "line one" not in r.content, "old text 'line one' still present"

def test_has_three_lines():
    f = data.get("_diag/llm_file_test.txt")
    r = f.read()
    assert "line alpha" in r.content, "missing 'line alpha'"
    assert "line two" in r.content, "missing 'line two'"
    assert "line three" in r.content, "missing 'line three'"

check("file_exists", test_file_exists)
check("edit_applied", test_edit_applied)
check("has_three_lines", test_has_three_lines)

print(json.dumps(results))
```
