# CogOS Diagnostics Runner — inline smoke tests for all capabilities.
# Runs in the Python sandbox. All capabilities injected as globals.

import time

def _now():
    t = time.gmtime()
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
        disk.get("_diag/test.txt").write("hello diagnostics")
        r = disk.get("_diag/test.txt").read()
        if hasattr(r, "error"):
            raise Exception(str(r.error))
        if r.content != "hello diagnostics":
            raise Exception("got " + repr(r.content))
    checks.append(check("write_read", test_write_read))

    def test_overwrite():
        disk.get("_diag/test.txt").write("version 2")
        r = disk.get("_diag/test.txt").read()
        if r.content != "version 2":
            raise Exception("got " + repr(r.content))
    checks.append(check("overwrite", test_overwrite))

    def test_edit():
        disk.get("_diag/edit.txt").write("the quick brown fox")
        disk.get("_diag/edit.txt").edit(old="brown", new="red")
        r = disk.get("_diag/edit.txt").read()
        if "red fox" not in r.content:
            raise Exception("got " + repr(r.content))
    checks.append(check("edit", test_edit))

    def test_grep():
        disk.get("_diag/grep.txt").write("MARKER_DIAG_TEST")
        results = disk.grep("MARKER_DIAG_TEST")
        if not isinstance(results, list) or len(results) == 0:
            raise Exception("grep returned " + repr(results))
    checks.append(check("grep", test_grep))

    def test_glob():
        results = disk.glob("_diag/*.txt")
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

def diag_child_exit():
    """Test child exit notification and handle.runs()."""
    checks = []

    def test_spawn_recv_wired():
        h = procs.spawn("_diag/exit/test", content='print("child done")', executor="python", mode="one_shot", capabilities={})
        if hasattr(h, "error"):
            raise Exception(str(h.error))
        msgs = h.recv(limit=5)
        if not isinstance(msgs, list):
            raise Exception("recv returned " + str(type(msgs)))
    checks.append(check("spawn_recv_wired", test_spawn_recv_wired))

    def test_handle_runs():
        h = procs.get(name="_diag/exit/test")
        if hasattr(h, "error"):
            raise Exception(str(h.error))
        runs = h.runs(limit=3)
        if not isinstance(runs, list):
            raise Exception("runs returned " + str(type(runs)))
    checks.append(check("handle_runs", test_handle_runs))

    return checks

def diag_me():
    """Test me process scope scratch/log/tmp."""
    checks = []

    def test_process_scratch():
        me.process().scratch().write("scratch data")
        r = me.process().scratch().read()
        if r is None:
            raise Exception("scratch read returned None")
        if r != "scratch data":
            raise Exception("got " + repr(r))
    checks.append(check("process_scratch", test_process_scratch))

    def test_process_tmp():
        me.process().tmp().write("tmp data")
        r = me.process().tmp().read()
        if r is None:
            raise Exception("tmp read returned None")
    checks.append(check("process_tmp", test_process_tmp))

    def test_process_log():
        me.process().log().write("log entry")
        r = me.process().log().read()
        if r is None:
            raise Exception("log read returned None")
    checks.append(check("process_log", test_process_log))

    return checks

def diag_stdlib():
    """Test time, json roundtrip."""
    checks = []

    def test_time():
        t = time.time()
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
        if web_search is None:
            raise Exception("web_search is None")
    checks.append(check("search_wired", test_search))

    return checks

def diag_blob():
    """Test blob upload/download."""
    checks = []
    def test_upload_download():
        ref = blob.upload("test content", "_diag_blob")
        if hasattr(ref, "error") and ref.error:
            raise Exception(str(ref.error))
        r = blob.download(ref.key)
        if hasattr(r, "error") and r.error:
            raise Exception(str(r.error))
        content = r.data if hasattr(r, "data") else str(r)
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        if "test content" not in content:
            raise Exception("mismatch: " + repr(content)[:100])
    checks.append(check("upload_download", test_upload_download))
    return checks

def diag_image():
    """Test image capability — manipulation, compositing, generation, analysis."""
    import base64
    checks = []

    def test_wired():
        if image is None:
            raise Exception("image is None")
        for method in ("resize", "crop", "rotate", "convert", "thumbnail",
                        "overlay_text", "watermark", "combine",
                        "describe", "analyze", "extract_text",
                        "generate", "edit", "variations"):
            if not hasattr(image, method):
                raise Exception("missing method: " + method)
    checks.append(check("wired", test_wired))

    # Minimal 2x2 PNG for manipulation/analysis tests
    _TEST_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVQI12P4z8BQDwAEgAF/"
        "QualzQAAAABJRU5ErkJggg=="
    )

    # Upload test image
    test_key = [None]
    def test_upload():
        ref = blob.upload(_TEST_PNG, "_diag_image_test.png", content_type="image/png")
        if hasattr(ref, "error") and ref.error:
            raise Exception(str(ref.error))
        test_key[0] = ref.key
    checks.append(check("upload_test_image", test_upload))

    # -- Manipulation --
    def test_resize():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.resize(test_key[0], width=4)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("resize", test_resize))

    def test_crop():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.crop(test_key[0], left=0, top=0, right=1, bottom=1)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("crop", test_crop))

    def test_rotate():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.rotate(test_key[0], degrees=90)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("rotate", test_rotate))

    def test_thumbnail():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.thumbnail(test_key[0], max_size=1)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("thumbnail", test_thumbnail))

    def test_convert():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.convert(test_key[0], format="JPEG")
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("convert", test_convert))

    # -- Compositing --
    def test_overlay_text():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.overlay_text(test_key[0], text="hi", position="center", font_size=10)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("overlay_text", test_overlay_text))

    def test_combine():
        if test_key[0] is None:
            raise Exception("skipped — no test image")
        r = image.combine([test_key[0], test_key[0]], layout="horizontal")
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("combine", test_combine))

    # -- Generation (Gemini) --
    gen_key = [None]
    def test_generate():
        r = image.generate("a small red circle on white background")
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
        if not hasattr(r, "key") or not r.key:
            raise Exception("no key in result")
        gen_key[0] = r.key
    checks.append(check("generate", test_generate))

    def test_edit():
        key = gen_key[0] or test_key[0]
        if key is None:
            raise Exception("skipped — no image to edit")
        r = image.edit(key, "add a blue border")
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("edit", test_edit))

    # -- Analysis (Gemini Vision) --
    def test_describe():
        key = gen_key[0] or test_key[0]
        if key is None:
            raise Exception("skipped — no image")
        r = image.describe(key)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("describe", test_describe))

    def test_analyze():
        key = gen_key[0] or test_key[0]
        if key is None:
            raise Exception("skipped — no image")
        r = image.analyze(key, "What color is this image?")
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("analyze", test_analyze))

    def test_extract_text():
        key = gen_key[0] or test_key[0]
        if key is None:
            raise Exception("skipped — no image")
        r = image.extract_text(key)
        if hasattr(r, "error") and r.error:
            raise Exception(r.error)
    checks.append(check("extract_text", test_extract_text))

    return checks

def diag_email():
    checks = []
    def test_wired():
        if email is None:
            raise Exception("email is None")
    checks.append(check("wired", test_wired))
    return checks

def diag_asana():
    """Test Asana capability — read-only operations."""
    checks = []

    def test_wired():
        if asana is None:
            raise Exception("asana is None")
    checks.append(check("wired", test_wired))

    def test_list_workspaces():
        ws = asana.list_workspaces()
        if hasattr(ws, "error"):
            raise Exception(str(ws.error))
        if not isinstance(ws, list):
            raise Exception("expected list, got " + str(type(ws)))
        if len(ws) == 0:
            raise Exception("no workspaces found")
    checks.append(check("list_workspaces", test_list_workspaces))

    def test_list_projects():
        ws = asana.list_workspaces()
        if hasattr(ws, "error") or not ws:
            raise Exception("need workspaces first")
        projects = asana.list_projects(workspace=ws[0]["id"], limit=5)
        if hasattr(projects, "error"):
            raise Exception(str(projects.error))
        if not isinstance(projects, list):
            raise Exception("expected list, got " + str(type(projects)))
    checks.append(check("list_projects", test_list_projects))

    def test_my_tasks():
        tasks = asana.my_tasks(limit=5)
        if hasattr(tasks, "error"):
            raise Exception(str(tasks.error))
        if not isinstance(tasks, list):
            raise Exception("expected list, got " + str(type(tasks)))
    checks.append(check("my_tasks", test_my_tasks))

    def test_find_user():
        ws = asana.list_workspaces()
        if hasattr(ws, "error") or not ws:
            raise Exception("need workspaces first")
        users = asana.find_user(workspace=ws[0]["id"], query="a")
        if hasattr(users, "error"):
            raise Exception(str(users.error))
        if not isinstance(users, list):
            raise Exception("expected list, got " + str(type(users)))
    checks.append(check("find_user", test_find_user))

    def test_search_tasks():
        ws = asana.list_workspaces()
        if hasattr(ws, "error") or not ws:
            raise Exception("need workspaces first")
        results = asana.search_tasks(ws[0]["id"], "test", limit=5)
        if hasattr(results, "error"):
            raise Exception(str(results.error))
        if not isinstance(results, list):
            raise Exception("expected list, got " + str(type(results)))
    checks.append(check("search_tasks", test_search_tasks))

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

def diag_history():
    """Test history capability — query, failed, process history."""
    checks = []

    def test_query():
        results = history.query(limit=5)
        if not isinstance(results, list):
            raise Exception("query returned " + str(type(results)))
    checks.append(check("query", test_query))

    def test_failed():
        results = history.failed(limit=5)
        if not isinstance(results, list):
            raise Exception("failed returned " + str(type(results)))
    checks.append(check("failed", test_failed))

    def test_process_history():
        h = history.process("init")
        if hasattr(h, "error"):
            raise Exception(str(h.error))
        runs = h.runs(limit=3)
        if not isinstance(runs, list):
            raise Exception("runs returned " + str(type(runs)))
    checks.append(check("process_history", test_process_history))

    return checks

# ═══════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════

ALL_DIAGNOSTICS = {
    "files": diag_files,
    "channels": diag_channels,
    "procs": diag_procs,
    "child_exit": diag_child_exit,
    "me": diag_me,
    "builtins": diag_stdlib,
    "discord": diag_discord,
    "web": diag_web,
    "blob": diag_blob,
    "image": diag_image,
    "email": diag_email,
    "asana": diag_asana,
    "github": diag_github,
    "alerts": diag_alerts,
    "history": diag_history,
}

# Only run when triggered via system:diagnostics channel
_channel = event.get("channel_name", "") if event else ""
if _channel != "system:diagnostics":
    print("Ignoring wakeup from " + _channel)
else:
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
    prev_raw = disk.get("current.json").read()
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
    disk.get("current.json").write(json.dumps(results))

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
    disk.get("current.md").write("\n".join(md))

    # log.md (prepend)
    log_line = "## " + timestamp + " — " + str(passed) + "/" + str(total) + " PASS"
    log_prev = disk.get("log.md").read()
    log_content = log_prev.content if hasattr(log_prev, "content") else ""
    disk.get("log.md").write(log_line + "\n" + log_content)

    # changelog
    if changes:
        cl_prev = disk.get("changelog.md").read()
        cl_content = cl_prev.content if hasattr(cl_prev, "content") else ""
        disk.get("changelog.md").write("## " + timestamp + "\n" + "\n".join(changes) + "\n\n" + cl_content)

    print(str(passed) + "/" + str(total) + " passed")
    for c in changes:
        print("  " + c)
