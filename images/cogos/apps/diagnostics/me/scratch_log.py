# Diagnostic: me/scratch_log.py
# Tests scratch, log, and tmp read/write via the `me` capability.


checks = []


def check(name, fn):
    try:
        fn()
        ms = 0
        checks.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = 0
        checks.append({"name": name, "status": "fail", "ms": ms, "error": str(e)})


# ── scratch read/write ───────────────────────────────────────

def test_scratch_write_read():
    f = me.scratch("diag_test_scratch")
    f.write("hello scratch")
    result = f.read()
    if hasattr(result, "error"):
        raise Exception("scratch read error: " + str(result.error))
    if result.content != "hello scratch":
        raise Exception("expected 'hello scratch', got: " + repr(result.content))

check("scratch_write_read", test_scratch_write_read)


# ── scratch append ───────────────────────────────────────────

def test_scratch_append():
    f = me.scratch("diag_test_scratch_append")
    f.write("line1\n")
    f.append("line2\n")
    result = f.read()
    if hasattr(result, "error"):
        raise Exception("scratch append read error: " + str(result.error))
    if "line1" not in result.content or "line2" not in result.content:
        raise Exception("append content missing expected lines: " + repr(result.content))

check("scratch_append", test_scratch_append)


# ── log write/read ───────────────────────────────────────────

def test_log_write_read():
    f = me.log("diag_test_log")
    f.write("log entry 1")
    result = f.read()
    if hasattr(result, "error"):
        raise Exception("log read error: " + str(result.error))
    if result.content != "log entry 1":
        raise Exception("expected 'log entry 1', got: " + repr(result.content))

check("log_write_read", test_log_write_read)


# ── log append ───────────────────────────────────────────────

def test_log_append():
    f = me.log("diag_test_log_append")
    f.write("first\n")
    f.append("second\n")
    result = f.read()
    if hasattr(result, "error"):
        raise Exception("log append read error: " + str(result.error))
    if "first" not in result.content or "second" not in result.content:
        raise Exception("log append missing lines: " + repr(result.content))

check("log_append", test_log_append)


# ── tmp write/read ───────────────────────────────────────────

def test_tmp_write_read():
    f = me.tmp("diag_test_tmp")
    f.write("tmp data")
    result = f.read()
    if hasattr(result, "error"):
        raise Exception("tmp read error: " + str(result.error))
    if result.content != "tmp data":
        raise Exception("expected 'tmp data', got: " + repr(result.content))

check("tmp_write_read", test_tmp_write_read)


print(json.dumps(checks))
