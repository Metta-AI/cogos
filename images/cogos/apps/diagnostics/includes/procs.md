@{mnt/boot/cogos/includes/code_mode.md}
@{mnt/boot/cogos/includes/procs.md}

# Diagnostic: includes/procs

Exercise the Procs API instructions above. Complete all tasks using `run_code()`.

## Tasks

1. **List processes**: Use `procs.list()` and print the result to see running processes.

2. **Spawn a child**: Spawn a child process with capabilities:
   ```python
   child = procs.spawn(
       "_diag/inc_procs_child",
       content="Print 'child_ok' and exit.",
       capabilities={"channels": channels.scope(names=["_diag/*"])},
   )
   ```

3. **Wait for child**: Use `child.wait()` to wait for the child to complete.

4. **Check status**: Print `child.status()` to confirm it completed.

5. **Read response**: Use `child.recv(limit=5)` to read any messages from the child.

```python verify
p = procs.get(name="_diag/inc_procs_child")
if hasattr(p, "error"):
    raise AssertionError("process not found: " + str(p.error))
status = p.status()
assert status == "completed", "expected completed, got: " + str(status)
```
