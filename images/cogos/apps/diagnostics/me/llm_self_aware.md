# Diagnostic: me/llm_self_aware

You are running as a CogOS diagnostic. Your job is to verify that the `me`
capability works for writing scratch notes and logs.

## Instructions

1. Use `me.scratch("diag_llm_scratch")` to get a file handle, then call
   `.write("llm was here")` on it.
2. Use `me.log("diag_llm_log")` to get a file handle, then call
   `.write("llm log entry")` on it.
3. Read both back using `.read()` and confirm the `.content` matches what
   you wrote.
4. Print a short confirmation message to stdout.

Do exactly the above steps, nothing more.

```python verify
import time

checks = []

def check(name, fn):
    t0 = time.time()
    try:
        fn()
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        checks.append({"name": name, "status": "fail", "ms": ms, "error": str(e)})

def verify_scratch():
    result = me.scratch("diag_llm_scratch").read()
    if hasattr(result, "error"):
        raise Exception("scratch read error: " + str(result.error))
    if "llm was here" not in result.content:
        raise Exception("scratch missing expected content: " + repr(result.content))

def verify_log():
    result = me.log("diag_llm_log").read()
    if hasattr(result, "error"):
        raise Exception("log read error: " + str(result.error))
    if "llm log entry" not in result.content:
        raise Exception("log missing expected content: " + repr(result.content))

check("scratch_exists", verify_scratch)
check("log_exists", verify_log)

print(json.dumps(checks))
```
