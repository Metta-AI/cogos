results = []

def check(name, fn):
    try:
        fn()
        results.append({"name": name, "status": "pass", "ms": 0})
    except Exception as e:
        results.append({"name": name, "status": "fail", "ms": 0, "error": str(e)[:300]})

def test_write_and_read():
    f = disk.get("_diag/rw_test.txt")
    f.write("hello world")
    r = f.read()
    assert not hasattr(r, "error"), "read error: " + str(getattr(r, "error", ""))
    assert r.content == "hello world", "expected 'hello world', got: " + repr(r.content)

def test_overwrite():
    f = disk.get("_diag/rw_test.txt")
    f.write("version2")
    r = f.read()
    assert r.content == "version2", "overwrite failed, got: " + repr(r.content)

def test_append():
    f = disk.get("_diag/rw_append.txt")
    f.write("line1\n")
    f.append("line2\n")
    f.append("line3\n")
    r = f.read()
    assert "line1" in r.content, "line1 missing"
    assert "line2" in r.content, "line2 missing"
    assert "line3" in r.content, "line3 missing"

def test_edit():
    f = disk.get("_diag/rw_edit.txt")
    f.write("the quick brown fox")
    f.edit("brown", "red")
    r = f.read()
    assert "red" in r.content, "edit did not apply, got: " + repr(r.content)
    assert "brown" not in r.content, "old text still present"

def test_read_nonexistent():
    f = disk.get("_diag/rw_nonexistent_0.txt")
    r = f.read()
    assert hasattr(r, "error"), "expected error for nonexistent file"

def test_write_empty():
    f = disk.get("_diag/rw_empty.txt")
    f.write("")
    r = f.read()
    assert not hasattr(r, "error"), "read error on empty file"
    assert r.content == "", "expected empty content, got: " + repr(r.content)

def test_write_large():
    f = disk.get("_diag/rw_large.txt")
    big = "x" * 10000
    f.write(big)
    r = f.read()
    assert len(r.content) == 10000, "expected 10000 chars, got " + str(len(r.content))

def test_write_special_chars():
    f = disk.get("_diag/rw_special.txt")
    content = 'line1\nline2\ttab\n"quotes" & symbols <>'
    f.write(content)
    r = f.read()
    assert r.content == content, "special chars mismatch"

def test_multiple_files():
    for i in range(5):
        f = disk.get("_diag/rw_multi_" + str(i) + ".txt")
        f.write("file_" + str(i))
    for i in range(5):
        f = disk.get("_diag/rw_multi_" + str(i) + ".txt")
        r = f.read()
        assert r.content == "file_" + str(i), "multi file mismatch at " + str(i)

def test_setup_search():
    disk.get("_diag/search/alpha.txt").write("the quick brown fox jumps over the lazy dog")
    disk.get("_diag/search/beta.txt").write("hello world from beta file")
    disk.get("_diag/search/gamma.py").write("print('hello from gamma')")
    disk.get("_diag/search/sub/deep.txt").write("deeply nested file content")
    disk.get("_diag/search/sub/deep.py").write("# deep python file\nx = 42")

def test_grep_basic():
    matches = disk.grep("hello")
    assert isinstance(matches, list), "grep should return list, got " + str(type(matches))
    keys = [m.key for m in matches]
    found = [k for k in keys if "_diag/search/" in k]
    assert len(found) >= 2, "expected at least 2 matches for 'hello', got " + str(len(found))

def test_glob_txt():
    matches = disk.glob("_diag/search/*.txt")
    assert isinstance(matches, list), "glob should return list"
    keys = [m.key for m in matches]
    txt_keys = [k for k in keys if k.endswith(".txt") and "_diag/search/" in k]
    assert len(txt_keys) >= 2, "expected at least 2 .txt files, got " + str(len(txt_keys))

def test_list():
    entries = disk.list()
    assert isinstance(entries, list), "list should return list"

def test_tree():
    tree_str = disk.tree()
    assert isinstance(tree_str, str), "tree should return string, got " + str(type(tree_str))
    assert len(tree_str) > 0, "tree output should not be empty"

check("write_and_read", test_write_and_read)
check("overwrite", test_overwrite)
check("append", test_append)
check("edit", test_edit)
check("read_nonexistent", test_read_nonexistent)
check("write_empty", test_write_empty)
check("write_large", test_write_large)
check("write_special_chars", test_write_special_chars)
check("multiple_files", test_multiple_files)
check("setup_search", test_setup_search)
check("grep_basic", test_grep_basic)
check("glob_txt", test_glob_txt)
check("list", test_list)
check("tree", test_tree)

print(json.dumps(results))
