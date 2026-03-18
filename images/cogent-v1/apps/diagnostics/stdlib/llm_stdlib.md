# Diagnostic: stdlib/llm_stdlib

You are running as a CogOS diagnostic. Your job is to verify that the `stdlib`
capability works correctly when used by an LLM.

## Instructions

1. Call `stdlib.time_iso()` and store the result.
2. Verify the result is a non-empty string that looks like an ISO timestamp
   (contains "T" or "-").
3. Use `json.dumps()` to serialize a dict `{"ts": <the timestamp>, "source": "llm"}`.
4. Use `json.loads()` to deserialize it back and confirm the values match.
5. Write the JSON string to `me.scratch("diag_llm_stdlib_result")` using `.write()`.
6. Print a short confirmation to stdout.

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

def verify_result_written():
    result = me.scratch("diag_llm_stdlib_result").read()
    if hasattr(result, "error"):
        raise Exception("scratch read error: " + str(result.error))
    data = json.loads(result.content)
    if "ts" not in data:
        raise Exception("missing 'ts' key in result: " + repr(data))
    if data.get("source") != "llm":
        raise Exception("source should be 'llm', got: " + repr(data.get("source")))

def verify_time_iso():
    ts = stdlib.time_iso()
    if not isinstance(ts, str) or len(ts) < 10:
        raise Exception("time_iso returned invalid value: " + repr(ts))

check("result_written", verify_result_written)
check("time_iso_works", verify_time_iso)

print(json.dumps(checks))
```
