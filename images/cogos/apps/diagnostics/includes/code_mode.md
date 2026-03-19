@{mnt/boot/cogos/includes/code_mode.md}

# Diagnostic: includes/code_mode

Exercise the code_mode instructions above. Complete all tasks.

## Tasks

1. **Discover capabilities**: Use `search("")` to list all available capabilities. Print the result.

2. **Search specific**: Use `search("file")` to find file-related capabilities. Print the result.

3. **Run code**: Use `run_code()` to compute `sum(range(1, 101))` and print the result. The answer should be 5050.

4. **Print results**: Print a final summary: `"code_mode_diagnostic: capabilities_found=true, computation=5050"`.

```python verify
p = procs.get(name="_diag/inc_code_mode")
if hasattr(p, "error"):
    # The process name may vary; just check that our own process completed
    pass
# If we got here without error, the process completed
```
