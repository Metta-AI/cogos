@{mnt/boot/cogos/includes/code_mode.md}

# Diagnostic: includes/history

Exercise the History API instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **Query recent runs**: Use `history.query(limit=5)` and print the results.

2. **Query failed runs**: Use `history.failed(limit=5)` and print the results.

3. **Process history**: Use `history.process("init")` to get a handle, then call `h.runs(limit=3)` and print the results.

```python verify
# Verify history.query works
results = history.query(limit=5)
assert isinstance(results, list), "expected list, got: " + str(type(results))

# Verify history.failed works
failed = history.failed(limit=5)
assert isinstance(failed, list), "expected list, got: " + str(type(failed))

# Verify history.process works
h = history.process("init")
assert not hasattr(h, "error"), "expected ProcessHistory, got error: " + str(getattr(h, "error", ""))
runs = h.runs(limit=3)
assert isinstance(runs, list), "expected list, got: " + str(type(runs))
```
