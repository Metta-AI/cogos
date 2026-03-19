# Diagnostic: LLM Spawn

You are running a diagnostic check for the CogOS process spawning system. Perform each step in order.

## Steps

1. **Spawn a child process** named `_diag/llm_child` using `procs.spawn()` with this Python code:
   ```python
   data.get("_diag/llm_spawn_output.txt").write("child was here")
   print("child process completed successfully")
   ```
   Use `executor="python"`, `mode="one_shot"`, and pass `capabilities={"data": data}`.

2. **Wait for the child** to complete using the handle's `.wait()` method.

3. **Check the child's status** using `.status()` — confirm it is `"completed"`.

4. **Read the child's stdout** using `.stdout(limit=1)` — confirm it contains "child process completed successfully".

5. **Read the file** the child created at `_diag/llm_spawn_output.txt` in `data` — confirm it contains "child was here".

6. **Spawn a second child** named `_diag/llm_child2` that sends a message back to the parent:
   ```python
   me.send({"status": "ok", "from": "child2"})
   print("child2 done")
   ```
   Use `capabilities={"me": me}`.

7. **Wait for child2**, then read messages from it using `handle.recv(limit=5)`. Confirm you received the message.

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

def test_child_file_written():
    f = data.get("_diag/llm_spawn_output.txt")
    r = f.read()
    assert not hasattr(r, "error"), "file not found: " + str(getattr(r, "error", ""))
    assert r.content == "child was here", "unexpected content: " + repr(r.content)

def test_child_process_completed():
    handle = procs.get(name="_diag/llm_child")
    assert not hasattr(handle, "error"), "could not get process: " + str(getattr(handle, "error", ""))
    status = handle.status()
    assert status == "completed", "expected completed, got: " + str(status)

def test_child2_exists():
    handle = procs.get(name="_diag/llm_child2")
    assert not hasattr(handle, "error"), "child2 not found: " + str(getattr(handle, "error", ""))
    status = handle.status()
    assert status == "completed", "child2 not completed: " + str(status)

check("child_file_written", test_child_file_written)
check("child_process_completed", test_child_process_completed)
check("child2_exists", test_child2_exists)

print(json.dumps(results))
```
