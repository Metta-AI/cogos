@{mnt/boot/cogos/includes/shell.md}

Compute 2 + 2 and write the result to `_diag/includes/shell_result.txt`.

```python verify
result = file.read("_diag/includes/shell_result.txt")
assert not hasattr(result, 'error'), "result file not written: " + str(getattr(result, 'error', ''))
assert "4" in result.content, "expected 4 in result, got: " + repr(result.content)
```
