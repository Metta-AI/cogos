# Diagnostic: stdlib/llm_stdlib

You are running as a CogOS diagnostic. Your job is to verify that the `stdlib`
capability works correctly when used by an LLM.

## Instructions

1. Call `stdlib.time.time()` and store the result.
2. Verify the result is a float greater than 1000000000.
3. Use `json.dumps()` to serialize a dict `{"ts": <the timestamp>, "source": "llm"}`.
4. Use `json.loads()` to deserialize it back and confirm the values match.
5. Write the JSON string to `me.scratch("diag_llm_stdlib_result")` using `.write()`.
6. Print a short confirmation to stdout.

Do exactly the above steps, nothing more.

```python verify
checks = []

def check(name, fn):
    try:
        fn()
        checks.append({"name": name, "status": "pass", "ms": 0})
    except Exception as e:
        checks.append({"name": name, "status": "fail", "ms": 0, "error": str(e)})

def verify_result_written():
    result = me.scratch("diag_llm_stdlib_result").read()
    if hasattr(result, "error"):
        raise Exception("scratch read error: " + str(result.error))
    data = json.loads(result.content)
    if "ts" not in data:
        raise Exception("missing 'ts' key in result: " + repr(data))
    if data.get("source") != "llm":
        raise Exception("source should be 'llm', got: " + repr(data.get("source")))

def verify_time():
    t = stdlib.time.time()
    if not isinstance(t, float) or t < 1000000000:
        raise Exception("stdlib.time.time() returned invalid value: " + repr(t))

check("result_written", verify_result_written)
check("time_works", verify_time)

print(json.dumps(checks))
```
