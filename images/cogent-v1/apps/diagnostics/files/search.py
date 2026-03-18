# Diagnostic: files/search.py
# Tests grep, glob, list, tree via data capability.
# Creates test files first, then searches them.

import time

results = []

def check(name, fn):
    t0 = time.time()
    try:
        fn()
        ms = int((time.time() - t0) * 1000)
        results.append({"name": name, "status": "pass", "ms": ms})
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        results.append({"name": name, "status": "fail", "ms": ms, "error": str(e)[:300]})

# ── Setup: create test files ─────────────────────────────────

def setup():
    data.get("_diag/search/alpha.txt").write("the quick brown fox jumps over the lazy dog")
    data.get("_diag/search/beta.txt").write("hello world from beta file")
    data.get("_diag/search/gamma.py").write("print('hello from gamma')")
    data.get("_diag/search/sub/deep.txt").write("deeply nested file content")
    data.get("_diag/search/sub/deep.py").write("# deep python file\nx = 42")

# ── Tests ────────────────────────────────────────────────────

def test_grep_basic():
    matches = data.grep("hello")
    assert isinstance(matches, list), "grep should return list, got " + str(type(matches))
    keys = [m.key for m in matches]
    found = [k for k in keys if "_diag/search/" in k]
    assert len(found) >= 2, "expected at least 2 matches for 'hello', got " + str(len(found))

def test_grep_no_match():
    matches = data.grep("zzz_nonexistent_pattern_xyz_12345")
    assert isinstance(matches, list), "grep should return list"
    diag_matches = [m for m in matches if "_diag/search/" in m.key]
    assert len(diag_matches) == 0, "expected 0 matches for nonsense pattern"

def test_grep_result_attributes():
    matches = data.grep("quick brown")
    found = [m for m in matches if "_diag/search/alpha.txt" in m.key]
    assert len(found) >= 1, "expected match in alpha.txt"
    m = found[0]
    assert hasattr(m, "key"), "GrepResult should have .key"
    assert hasattr(m, "matches"), "GrepResult should have .matches"

def test_glob_txt():
    matches = data.glob("_diag/search/*.txt")
    assert isinstance(matches, list), "glob should return list"
    keys = [m.key for m in matches]
    txt_keys = [k for k in keys if k.endswith(".txt") and "_diag/search/" in k]
    assert len(txt_keys) >= 2, "expected at least 2 .txt files, got " + str(len(txt_keys))

def test_glob_py():
    matches = data.glob("_diag/search/**/*.py")
    assert isinstance(matches, list), "glob should return list"
    keys = [m.key for m in matches]
    py_keys = [k for k in keys if k.endswith(".py") and "_diag/search/" in k]
    assert len(py_keys) >= 1, "expected at least 1 .py file in subdirs"

def test_glob_no_match():
    matches = data.glob("_diag/search/*.zzz_nonexistent")
    assert isinstance(matches, list), "glob should return list"
    assert len(matches) == 0, "expected 0 matches for .zzz_nonexistent"

def test_list():
    entries = data.list()
    assert isinstance(entries, list), "list should return list"
    keys = [e.key for e in entries]
    diag_keys = [k for k in keys if "_diag/search/" in k]
    assert len(diag_keys) >= 5, "expected at least 5 _diag/search files in list, got " + str(len(diag_keys))

def test_list_has_key_attr():
    entries = data.list()
    assert len(entries) > 0, "list returned empty"
    assert hasattr(entries[0], "key"), "list entries should have .key attribute"

def test_tree():
    tree_str = data.tree()
    assert isinstance(tree_str, str), "tree should return string, got " + str(type(tree_str))
    assert len(tree_str) > 0, "tree output should not be empty"
    assert "_diag" in tree_str, "tree should contain _diag directory"

# ── Run ──────────────────────────────────────────────────────

check("setup", setup)
check("grep_basic", test_grep_basic)
check("grep_no_match", test_grep_no_match)
check("grep_result_attributes", test_grep_result_attributes)
check("glob_txt", test_glob_txt)
check("glob_py", test_glob_py)
check("glob_no_match", test_glob_no_match)
check("list", test_list)
check("list_has_key_attr", test_list_has_key_attr)
check("tree", test_tree)

print(json.dumps(results))
