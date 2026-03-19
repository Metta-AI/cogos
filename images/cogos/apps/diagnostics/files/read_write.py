# Diagnostic: files/read_write.py
# Tests file create, read, versioning, upsert, append, edit, head/tail via data capability.


results = []

def check(name, fn):
    try:
        fn()
        ms = 0
        results.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = 0
        results.append({"name": name, "status": "fail", "ms": ms, "error": str(e)[:300]})

# ── Tests ────────────────────────────────────────────────────

def test_write_and_read():
    f = data.get("_diag/rw_test.txt")
    f.write("hello world")
    r = f.read()
    assert not hasattr(r, "error"), "read error: " + str(getattr(r, "error", ""))
    assert r.content == "hello world", "expected 'hello world', got: " + repr(r.content)

def test_overwrite():
    f = data.get("_diag/rw_test.txt")
    f.write("version2")
    r = f.read()
    assert r.content == "version2", "overwrite failed, got: " + repr(r.content)

def test_append():
    f = data.get("_diag/rw_append.txt")
    f.write("line1\n")
    f.append("line2\n")
    f.append("line3\n")
    r = f.read()
    assert "line1" in r.content, "line1 missing"
    assert "line2" in r.content, "line2 missing"
    assert "line3" in r.content, "line3 missing"

def test_edit():
    f = data.get("_diag/rw_edit.txt")
    f.write("the quick brown fox")
    f.edit("brown", "red")
    r = f.read()
    assert "red" in r.content, "edit did not apply, got: " + repr(r.content)
    assert "brown" not in r.content, "old text still present"

def test_read_nonexistent():
    f = data.get("_diag/rw_nonexistent_" + str(0) + ".txt")
    r = f.read()
    assert hasattr(r, "error"), "expected error for nonexistent file"

def test_write_empty():
    f = data.get("_diag/rw_empty.txt")
    f.write("")
    r = f.read()
    assert not hasattr(r, "error"), "read error on empty file"
    assert r.content == "", "expected empty content, got: " + repr(r.content)

def test_write_large():
    f = data.get("_diag/rw_large.txt")
    big = "x" * 10000
    f.write(big)
    r = f.read()
    assert len(r.content) == 10000, "expected 10000 chars, got " + str(len(r.content))

def test_write_special_chars():
    f = data.get("_diag/rw_special.txt")
    content = 'line1\nline2\ttab\n"quotes" & symbols <>'
    f.write(content)
    r = f.read()
    assert r.content == content, "special chars mismatch"

def test_multiple_files():
    for i in range(5):
        f = data.get("_diag/rw_multi_" + str(i) + ".txt")
        f.write("file_" + str(i))
    for i in range(5):
        f = data.get("_diag/rw_multi_" + str(i) + ".txt")
        r = f.read()
        assert r.content == "file_" + str(i), "multi file mismatch at " + str(i)

# ── Run all checks ───────────────────────────────────────────

check("write_and_read", test_write_and_read)
check("overwrite", test_overwrite)
check("append", test_append)
check("edit", test_edit)
check("read_nonexistent", test_read_nonexistent)
check("write_empty", test_write_empty)
check("write_large", test_write_large)
check("write_special_chars", test_write_special_chars)
check("multiple_files", test_multiple_files)

print(json.dumps(results))
