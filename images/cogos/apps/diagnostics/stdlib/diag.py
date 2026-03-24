checks = []

def check(name, fn):
    try:
        fn()
        checks.append({"name": name, "status": "pass", "ms": 0})
    except Exception as e:
        checks.append({"name": name, "status": "fail", "ms": 0, "error": str(e)[:300]})

def test_time_iso():
    t = time.time()
    if not isinstance(t, float):
        raise Exception("time.time() should return float, got: " + str(type(t)))
    if t < 1000000000:
        raise Exception("time.time() returned suspiciously small value: " + repr(t))

def test_json_roundtrip():
    data = {"key": "value", "num": 42, "nested": [1, 2, 3], "flag": True}
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    if decoded != data:
        raise Exception("json roundtrip mismatch: " + repr(decoded) + " != " + repr(data))

def test_json_edge_cases():
    for val in [[], {}, "", 0, None, False]:
        rt = json.loads(json.dumps(val))
        if rt != val:
            raise Exception("json roundtrip failed for: " + repr(val))
    udata = {"emoji": "hello", "accents": "cafe"}
    rt = json.loads(json.dumps(udata))
    if rt != udata:
        raise Exception("json unicode roundtrip failed")

def test_basic_math():
    if 2 + 2 != 4:
        raise Exception("2 + 2 != 4")
    if 10 * 3 != 30:
        raise Exception("10 * 3 != 30")
    if 100 / 4 != 25.0:
        raise Exception("100 / 4 != 25.0")
    if 2 ** 10 != 1024:
        raise Exception("2 ** 10 != 1024")
    if abs(-7) != 7:
        raise Exception("abs(-7) != 7")
    if max(3, 1, 4, 1, 5) != 5:
        raise Exception("max failed")

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

check("time_iso", test_time_iso)
check("json_roundtrip", test_json_roundtrip)
check("json_edge_cases", test_json_edge_cases)
check("basic_math", test_basic_math)
check("string_ops", test_string_ops)

print(json.dumps(checks))
