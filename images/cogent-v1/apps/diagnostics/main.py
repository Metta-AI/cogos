# CogOS Diagnostics Runner — inline smoke tests for all capabilities.
# Runs in the Python sandbox. All capabilities injected as globals.

def _now():
    t = stdlib.time.gmtime()
    return (str(t.tm_year) + "-" + str(t.tm_mon).zfill(2) + "-"
            + str(t.tm_mday).zfill(2) + "T" + str(t.tm_hour).zfill(2)
            + ":" + str(t.tm_min).zfill(2) + ":" + str(t.tm_sec).zfill(2) + "Z")

def check(name, fn):
    """Run a check function, return result dict."""
    try:
        fn()
        return {"name": name, "status": "pass", "ms": 0}
    except Exception as e:
        return {"name": name, "status": "fail", "ms": 0, "error": str(e)[:300]}

# ═══════════════════════════════════════════════════════════
# DIAGNOSTICS — each returns a list of check results
# ═══════════════════════════════════════════════════════════

def diag_files():
    """Test file/dir read, write, edit, search."""
    checks = []

    def test_write_read():
        data.get("_diag/test.txt").write("hello diagnostics")
        r = data.get("_diag/test.txt").read()
        if hasattr(r, "error"):
            raise Exception(str(r.error))
        if r.content != "hello diagnostics":
            raise Exception("got " + repr(r.content))
    checks.append(check("write_read", test_write_read))

    def test_overwrite():
        data.get("_diag/test.txt").write("version 2")
        r = data.get("_diag/test.txt").read()
        if r.content != "version 2":
            raise Exception("got " + repr(r.content))
    checks.append(check("overwrite", test_overwrite))

    def test_edit():
        data.get("_diag/edit.txt").write("the quick brown fox")
        data.get("_diag/edit.txt").edit("brown", "red")
        r = data.get("_diag/edit.txt").read()
        if "red fox" not in r.content:
            raise Exception("got " + repr(r.content))
    checks.append(check("edit", test_edit))

    def test_grep():
        data.get("_diag/grep.txt").write("MARKER_DIAG_TEST")
        results = data.grep("MARKER_DIAG_TEST")
        if not isinstance(results, list) or len(results) == 0:
            raise Exception("grep returned " + repr(results))
    checks.append(check("grep", test_grep))

    def test_glob():
        results = data.glob("_diag/*.txt")
        if not isinstance(results, list):
            raise Exception("glob returned " + repr(results))
    checks.append(check("glob", test_glob))

    return checks

def diag_channels():
    """Test channel create, send, read."""
    checks = []

    def test_create_send_read():
        channels.create("_diag:ch:test")
        channels.send("_diag:ch:test", {"seq": 1})
        channels.send("_diag:ch:test", {"seq": 2})
        msgs = channels.read("_diag:ch:test", limit=10)
        if not isinstance(msgs, list) or len(msgs) < 2:
            raise Exception("expected 2+ msgs, got " + str(len(msgs) if isinstance(msgs, list) else msgs))
    checks.append(check("create_send_read", test_create_send_read))

    def test_list():
        ch_list = channels.list()
        if not isinstance(ch_list, list):
            raise Exception("list returned " + repr(ch_list))
    checks.append(check("list", test_list))

    return checks

def diag_procs():
    """Test procs list, get, spawn."""
    checks = []

    def test_list():
        result = procs.list()
        if not isinstance(result, list):
            raise Exception("list returned " + repr(result))
    checks.append(check("list", test_list))

    def test_spawn():
        h = procs.spawn("_diag/proc/test", content='print("ok")', executor="python", mode="one_shot", capabilities={})
        if hasattr(h, "error"):
            raise Exception(str(h.error))
    checks.append(check("spawn", test_spawn))

    def test_get():
        h = procs.get(name="_diag/proc/test")
        if hasattr(h, "error"):
            raise Exception(str(h.error))
    checks.append(check("get", test_get))

    return checks

def diag_me():
    """Test me scratch/log/tmp."""
    checks = []

    def test_scratch():
        me.scratch("_diag_test.txt").write("scratch data")
        r = me.scratch("_diag_test.txt").read()
        if hasattr(r, "error"):
            raise Exception(str(r.error))
        if r.content != "scratch data":
            raise Exception("got " + repr(r.content))
    checks.append(check("scratch", test_scratch))

    def test_tmp():
        me.tmp("_diag_test.txt").write("tmp data")
        r = me.tmp("_diag_test.txt").read()
        if hasattr(r, "error"):
            raise Exception(str(r.error))
    checks.append(check("tmp", test_tmp))

    return checks

def diag_stdlib():
    """Test stdlib.time, json roundtrip."""
    checks = []

    def test_time():
        t = stdlib.time.time()
        if not isinstance(t, float) or t < 1000000000:
            raise Exception("got " + repr(t))
    checks.append(check("time", test_time))

    def test_json():
        d = {"key": "value", "num": 42}
        rt = json.loads(json.dumps(d))
        if rt != d:
            raise Exception("roundtrip mismatch")
    checks.append(check("json_roundtrip", test_json))

    return checks

def diag_discord():
    """Test discord read-only ops."""
    checks = []
    def test_wired():
        if discord is None:
            raise Exception("discord is None")
    checks.append(check("wired", test_wired))
    return checks

def diag_web():
    """Test web_fetch and web_search."""
    checks = []

    def test_fetch():
        r = web_fetch.fetch("https://httpbin.org/get")
        if hasattr(r, "error") and r.error:
            raise Exception(str(r.error))
    checks.append(check("fetch", test_fetch))

    def test_search():
        r = web_search.search("test")
        if hasattr(r, "error") and r.error:
            raise Exception(str(r.error))
    checks.append(check("search", test_search))

    return checks

def diag_blob():
    """Test blob upload/download."""
    checks = []
    def test_upload_download():
        blob.upload("_diag_blob", "test content")
        r = blob.download("_diag_blob")
        if hasattr(r, "error") and r.error:
            raise Exception(str(r.error))
        content = r.content if hasattr(r, "content") else str(r)
        if "test content" not in content:
            raise Exception("mismatch: " + repr(content)[:100])
    checks.append(check("upload_download", test_upload_download))
    return checks

def diag_image():
    """Test image capability is wired."""
    checks = []
    def test_wired():
        if image is None:
            raise Exception("image is None")
    checks.append(check("wired", test_wired))
    return checks

def diag_email():
    checks = []
    def test_wired():
        if email is None:
            raise Exception("email is None")
    checks.append(check("wired", test_wired))
    return checks

def diag_asana():
    checks = []
    def test_wired():
        if asana is None:
            raise Exception("asana is None")
    checks.append(check("wired", test_wired))
    return checks

def diag_github():
    checks = []
    def test_wired():
        if github is None:
            raise Exception("github is None")
    checks.append(check("wired", test_wired))
    return checks

def diag_alerts():
    checks = []
    def test_wired():
        if alerts is None:
            raise Exception("alerts is None")
    checks.append(check("wired", test_wired))
    return checks

# ═══════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════

ALL_DIAGNOSTICS = {
    "files": diag_files,
    "channels": diag_channels,
    "procs": diag_procs,
    "me": diag_me,
    "stdlib": diag_stdlib,
    "discord": diag_discord,
    "web": diag_web,
    "blob": diag_blob,
    "image": diag_image,
    "email": diag_email,
    "asana": diag_asana,
    "github": diag_github,
    "alerts": diag_alerts,
}

timestamp = _now()
print("Diagnostics starting at " + timestamp)

total = 0
passed = 0
categories = {}

for cat in sorted(ALL_DIAGNOSTICS):
    fn = ALL_DIAGNOSTICS[cat]
    try:
        checks = fn()
    except Exception as e:
        checks = [{"name": "run", "status": "fail", "ms": 0, "error": str(e)[:300]}]

    cat_pass = all(c.get("status") == "pass" for c in checks)
    categories[cat] = {
        "status": "pass" if cat_pass else "fail",
        "diagnostics": [{"name": cat, "status": "pass" if cat_pass else "fail", "checks": checks}],
    }
    for c in checks:
        total += 1
        if c.get("status") == "pass":
            passed += 1

results = {
    "timestamp": timestamp,
    "summary": {"total": total, "pass": passed, "fail": total - passed},
    "categories": categories,
}

# Read previous results for diffing
prev = None
prev_raw = data.get("current.json").read()
if not hasattr(prev_raw, "error"):
    try:
        prev = json.loads(prev_raw.content)
    except (ValueError, TypeError):
        pass

# Diff
def _flat(r):
    d = {}
    for cat in r.get("categories", {}):
        for diag in r["categories"][cat]["diagnostics"]:
            for ck in diag.get("checks", []):
                d[cat + ":" + ck.get("name", "?")] = ck.get("status")
    return d

changes = []
if prev:
    p = _flat(prev)
    c = _flat(results)
    for k in sorted(set(list(p.keys()) + list(c.keys()))):
        if k in c and k not in p:
            changes.append("- ADDED: " + k)
        elif k in p and k not in c:
            changes.append("- REMOVED: " + k)
        elif p.get(k) == "pass" and c.get(k) != "pass":
            changes.append("- FAILING: " + k)
        elif p.get(k) != "pass" and c.get(k) == "pass":
            changes.append("- FIXED: " + k)

# Write reports
data.get("current.json").write(json.dumps(results))

# current.md
md = ["# Diagnostics — " + timestamp, "**" + str(passed) + "/" + str(total) + " PASS**", ""]
for cat in sorted(categories):
    c = categories[cat]
    diags = c["diagnostics"]
    p = sum(1 for d in diags if d["status"] == "pass")
    md.append("## " + cat + " (" + str(p) + "/" + str(len(diags)) + " " + ("PASS" if c["status"] == "pass" else "FAIL") + ")")
    for d in diags:
        for ck in d.get("checks", []):
            mark = "[x]" if ck.get("status") == "pass" else "[ ]"
            line = "- " + mark + " " + ck.get("name", "?")
            if ck.get("error"):
                line += " — " + str(ck["error"])[:150]
            md.append(line)
    md.append("")
data.get("current.md").write("\n".join(md))

# log.md (prepend)
log_line = "## " + timestamp + " — " + str(passed) + "/" + str(total) + " PASS"
log_prev = data.get("log.md").read()
log_content = log_prev.content if hasattr(log_prev, "content") else ""
data.get("log.md").write(log_line + "\n" + log_content)

# changelog
if changes:
    cl_prev = data.get("changelog.md").read()
    cl_content = cl_prev.content if hasattr(cl_prev, "content") else ""
    data.get("changelog.md").write("## " + timestamp + "\n" + "\n".join(changes) + "\n\n" + cl_content)

print(str(passed) + "/" + str(total) + " passed")
for c in changes:
    print("  " + c)
