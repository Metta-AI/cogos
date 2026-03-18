# Diagnostic: scheduler/dispatch.py
# Tests match_messages() and select_processes() run without error.

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


# ── match_messages ───────────────────────────────────────────

def test_match_messages():
    result = scheduler.match_messages()
    if not isinstance(result, int):
        raise Exception("match_messages() should return int, got: " + str(type(result)))

check("match_messages", test_match_messages)


# ── select_processes ─────────────────────────────────────────

def test_select_processes():
    result = scheduler.select_processes(slots=1)
    if not isinstance(result, list):
        raise Exception("select_processes() should return list, got: " + str(type(result)))

check("select_processes", test_select_processes)


print(json.dumps(checks))
