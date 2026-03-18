# CogOS Diagnostics Runner
# Discovers .py diagnostics, executes them inline, writes results.
# Runs in the Python sandbox — capabilities injected as globals.
# Skips .md (LLM) diagnostics to avoid token cost and throttling.

# ── Capability map: category -> cap names to inject ──────────

_CAPS = {
    "files":     {"file": file, "dir": dir, "data": data},
    "channels":  {"channels": channels},
    "procs":     {"procs": procs, "channels": channels},
    "me":        {"me": me},
    "scheduler": {"channels": channels, "procs": procs},
    "stdlib":    {"stdlib": stdlib},
    "discord":   {"discord": discord},
    "web":       {"web_fetch": web_fetch, "web_search": web_search},
    "blob":      {"blob": blob},
    "image":     {"image": image},
    "email":     {"email": email},
    "asana":     {"asana": asana},
    "github":    {"github": github},
    "alerts":    {"alerts": alerts},
}

_SKIP = {"main.py", "cog.py"}

# Capture sandbox builtins + capabilities for passing to diagnostic exec.
# Only reference names that _SAFE_BUILTINS actually provides.
_RUNNER_NS = {
    "json": json, "print": print, "exit": exit,
    "len": len, "range": range, "str": str, "int": int,
    "float": float, "bool": bool, "list": list, "dict": dict,
    "tuple": tuple, "set": set,
    "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
    "repr": repr, "sorted": sorted,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "min": min, "max": max, "sum": sum, "abs": abs, "round": round,
    "True": True, "False": False, "None": None,
    "Exception": Exception,
    "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
    "me": me, "stdlib": stdlib, "data": data,
    "procs": procs, "dir": dir, "file": file, "channels": channels,
    "discord": discord, "email": email, "asana": asana, "github": github,
    "web": web, "web_search": web_search, "web_fetch": web_fetch,
    "blob": blob, "image": image, "alerts": alerts,
}

def _now():
    t = stdlib.time.gmtime()
    return (str(t.tm_year) + "-" + str(t.tm_mon).zfill(2) + "-"
            + str(t.tm_mday).zfill(2) + "T" + str(t.tm_hour).zfill(2)
            + ":" + str(t.tm_min).zfill(2) + ":" + str(t.tm_sec).zfill(2) + "Z")

# ── Discovery ────────────────────────────────────────────────

def discover():
    """Find .py diagnostic files by category. Returns {cat: [{name, path}]}."""
    result = {}
    prefix = ""
    if hasattr(source, "_scope"):
        prefix = source._scope.get("prefix", "")

    for entry in source.list(limit=500):
        key = entry.key if hasattr(entry, "key") else str(entry)
        rel = key[len(prefix):] if prefix and key.startswith(prefix) else key

        if "/" not in rel or not rel.endswith(".py"):
            continue
        parts = rel.split("/")
        if parts[-1] in _SKIP:
            continue

        cat = parts[0]
        if cat not in result:
            result[cat] = []
        result[cat].append({"name": parts[-1], "path": rel})

    return result

# ── Execute one diagnostic ───────────────────────────────────

def run_one(cat, diag):
    """Execute a .py diagnostic inline. Returns check results list."""
    content_result = source.get(diag["path"]).read()
    if hasattr(content_result, "error"):
        return [{"name": "read", "status": "fail", "ms": 0,
                 "error": "cannot read " + diag["path"]}]

    code = content_result.content

    # Build namespace from captured runner scope
    ns = dict(_RUNNER_NS)

    # Add category-specific caps
    caps = _CAPS.get(cat, {})
    ns.update(caps)

    # Capture stdout
    _output = []
    def _print(*args, **kwargs):
        _output.append(" ".join(str(a) for a in args))
    ns["print"] = _print

    t0 = stdlib.time.time()
    try:
        exec(code, ns)
        ms = int((stdlib.time.time() - t0) * 1000)
    except Exception as e:
        ms = int((stdlib.time.time() - t0) * 1000)
        return [{"name": "run", "status": "fail", "ms": ms,
                 "error": str(e)[:500]}]

    # Parse JSON output from captured prints
    for line in _output:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError):
            pass

    return [{"name": "run", "status": "pass", "ms": ms}]

# ── Report helpers ───────────────────────────────────────────

def make_md(results):
    ts = results["timestamp"]
    s = results["summary"]
    lines = ["# Diagnostics — " + ts,
             "**" + str(s["pass"]) + "/" + str(s["total"]) + " PASS**", ""]
    for cat in sorted(results["categories"]):
        c = results["categories"][cat]
        diags = c["diagnostics"]
        p = sum(1 for d in diags if d["status"] == "pass")
        label = "PASS" if c["status"] == "pass" else "FAIL"
        lines.append("## " + cat + " (" + str(p) + "/" + str(len(diags)) + " " + label + ")")
        for d in diags:
            mark = "[x]" if d["status"] == "pass" else "[ ]"
            lines.append("- " + mark + " " + d["name"])
            if d["status"] == "fail":
                for ck in d.get("checks", []):
                    if ck.get("error"):
                        lines.append("  > " + str(ck["error"])[:200])
        lines.append("")
    return "\n".join(lines)

def make_log(results):
    ts = results["timestamp"]
    s = results["summary"]
    line = "## " + ts + " — " + str(s["pass"]) + "/" + str(s["total"]) + " PASS"
    fails = []
    for cat in sorted(results["categories"]):
        for d in results["categories"][cat]["diagnostics"]:
            for ck in d.get("checks", []):
                if ck.get("status") == "fail":
                    fails.append("- FAIL " + cat + "/" + d["name"] + ":" + ck.get("name", "?") + " — " + str(ck.get("error", ""))[:200])
    if fails:
        return line + "\n" + "\n".join(fails) + "\n"
    return line + "\n(all pass)\n"

def diff_results(prev, curr):
    def flat(r):
        d = {}
        for cat in r.get("categories", {}):
            for diag in r["categories"][cat]["diagnostics"]:
                for ck in diag.get("checks", []):
                    d[cat + "/" + diag["name"] + ":" + ck.get("name", "?")] = ck.get("status")
        return d
    changes = []
    p = flat(prev) if prev else {}
    c = flat(curr)
    for k in sorted(set(list(p.keys()) + list(c.keys()))):
        if k in c and k not in p:
            changes.append("- ADDED: " + k)
        elif k in p and k not in c:
            changes.append("- REMOVED: " + k)
        elif p.get(k) == "pass" and c.get(k) != "pass":
            changes.append("- FAILING: " + k)
        elif p.get(k) != "pass" and c.get(k) == "pass":
            changes.append("- FIXED: " + k)
    return changes

# ── Main ─────────────────────────────────────────────────────

timestamp = _now()
print("Diagnostics starting at " + timestamp)

diags_by_cat = discover()
if not diags_by_cat:
    print("WARN: no diagnostics found")
    data.get("current.json").write(json.dumps({"error": "no diagnostics found"}))
    exit()

total_diags = sum(len(v) for v in diags_by_cat.values())
print("Found " + str(total_diags) + " .py diagnostics")

# Run all diagnostics inline
cat_results = {}
for cat in sorted(diags_by_cat):
    cat_results[cat] = []
    for diag in diags_by_cat[cat]:
        checks = run_one(cat, diag)
        status = "pass" if all(c.get("status") == "pass" for c in checks) else "fail"
        cat_results[cat].append({"name": diag["name"], "status": status, "checks": checks})

# Build report
total = 0
passed = 0
categories = {}
for cat in sorted(cat_results):
    diags = cat_results[cat]
    cat_pass = all(d["status"] == "pass" for d in diags)
    categories[cat] = {"status": "pass" if cat_pass else "fail", "diagnostics": diags}
    for d in diags:
        for ck in d.get("checks", []):
            total += 1
            if ck.get("status") == "pass":
                passed += 1

results = {
    "timestamp": timestamp,
    "duration_ms": 0,
    "summary": {"total": total, "pass": passed, "fail": total - passed},
    "categories": categories,
}

# Diff
prev = None
prev_raw = data.get("current.json").read()
if not hasattr(prev_raw, "error"):
    try:
        prev = json.loads(prev_raw.content)
    except (ValueError, TypeError):
        pass

changes = diff_results(prev, results)

# Write reports (use write not append — append has a DB column bug)
data.get("current.json").write(json.dumps(results))
data.get("current.md").write(make_md(results))

# For log and changelog, read existing content and prepend new entry
log_existing = data.get("log.md").read()
log_prev = log_existing.content if hasattr(log_existing, "content") else ""
data.get("log.md").write(make_log(results) + "\n" + log_prev)

if changes:
    cl_existing = data.get("changelog.md").read()
    cl_prev = cl_existing.content if hasattr(cl_existing, "content") else ""
    data.get("changelog.md").write("## " + timestamp + "\n" + "\n".join(changes) + "\n\n" + cl_prev)

print(str(passed) + "/" + str(total) + " passed")
if changes:
    for c in changes:
        print("  " + c)
