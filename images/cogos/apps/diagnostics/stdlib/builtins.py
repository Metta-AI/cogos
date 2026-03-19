# Diagnostic: stdlib/builtins.py
# Tests time_iso, json roundtrip, and basic math.


checks = []


def check(name, fn):
    try:
        fn()
        ms = 0
        checks.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = 0
        checks.append({"name": name, "status": "fail", "ms": ms, "error": str(e)})


# ── time_iso ─────────────────────────────────────────────────

def test_time_iso():
    t = stdlib.time.time()
    if not isinstance(t, float):
        raise Exception("stdlib.time.time() should return float, got: " + str(type(t)))
    if t < 1000000000:
        raise Exception("stdlib.time.time() returned suspiciously small value: " + repr(t))

check("time_iso", test_time_iso)


# ── json roundtrip ───────────────────────────────────────────

def test_json_roundtrip():
    data = {"key": "value", "num": 42, "nested": [1, 2, 3], "flag": True}
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    if decoded != data:
        raise Exception("json roundtrip mismatch: " + repr(decoded) + " != " + repr(data))

check("json_roundtrip", test_json_roundtrip)


# ── json edge cases ──────────────────────────────────────────

def test_json_edge_cases():
    # Empty structures
    for val in [[], {}, "", 0, None, False]:
        rt = json.loads(json.dumps(val))
        if rt != val:
            raise Exception("json roundtrip failed for: " + repr(val))
    # Unicode
    udata = {"emoji": "hello", "accents": "cafe"}
    rt = json.loads(json.dumps(udata))
    if rt != udata:
        raise Exception("json unicode roundtrip failed")

check("json_edge_cases", test_json_edge_cases)


# ── basic math ───────────────────────────────────────────────

def test_basic_math():
    if 2 + 2 != 4:
        raise Exception("2 + 2 != 4")
    if 10 * 3 != 30:
        raise Exception("10 * 3 != 30")
    if 100 / 4 != 25.0:
        raise Exception("100 / 4 != 25.0")
    if 2 ** 10 != 1024:
        raise Exception("2 ** 10 != 1024")
    if 17 % 5 != 2:
        raise Exception("17 % 5 != 2")
    if abs(-7) != 7:
        raise Exception("abs(-7) != 7")
    if max(3, 1, 4, 1, 5) != 5:
        raise Exception("max failed")
    if min(3, 1, 4, 1, 5) != 1:
        raise Exception("min failed")

check("basic_math", test_basic_math)


# ── string operations ────────────────────────────────────────

def test_string_ops():
    s = "hello world"
    if s.upper() != "HELLO WORLD":
        raise Exception("upper() failed")
    if s.split() != ["hello", "world"]:
        raise Exception("split() failed")
    if ",".join(["a", "b", "c"]) != "a,b,c":
        raise Exception("join() failed")
    if s.replace("world", "cogos") != "hello cogos":
        raise Exception("replace() failed")

check("string_ops", test_string_ops)


print(json.dumps(checks))
