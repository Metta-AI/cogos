# CogOS Diagnostics Runner
# Discovers all diagnostics, spawns them in parallel, collects results,
# diffs against previous run, and writes output files.
#
# Runs in the Python sandbox — only json (pre-loaded) and time are available.
# All capabilities are injected as globals.

import time

# ── Configuration ────────────────────────────────────────────

_CATEGORY_CAPS = {
    "files":     ["file", "dir", "files"],
    "channels":  ["channels"],
    "procs":     ["procs", "channels"],
    "me":        ["me"],
    "scheduler": ["scheduler", "channels", "procs"],
    "stdlib":    ["stdlib"],
    "discord":   ["discord"],
    "web":       ["web_fetch", "web_search"],
    "blob":      ["blob"],
    "image":     ["image"],
    "email":     ["email"],
    "asana":     ["asana"],
    "github":    ["github"],
    "alerts":    ["alerts"],
    "includes/files":       ["file", "dir", "files"],
    "includes/channels":    ["channels"],
    "includes/procs":       ["procs", "channels"],
    "includes/code_mode":   ["file", "dir"],
    "includes/escalate":    ["channels"],
    "includes/image":       ["image", "blob"],
    "includes/discord":     ["discord"],
    "includes/email":       ["email"],
    "includes/shell":       ["file", "dir", "files", "channels", "procs"],
    "includes/memory":      ["file", "dir"],
}

# Map capability names to injected globals
_cap_objects = {
    "me": me, "procs": procs, "dir": dir, "file": file, "files": files,
    "channels": channels, "scheduler": scheduler, "stdlib": stdlib,
    "discord": discord, "email": email, "asana": asana, "github": github,
    "web": web, "web_search": web_search, "web_fetch": web_fetch,
    "blob": blob, "image": image, "alerts": alerts, "data": data,
}

# Files to skip in the root diagnostics directory
_SKIP_FILES = {"main.py", "cog.py"}

# Timeout per diagnostic process (ms)
_DIAG_TIMEOUT_MS = 30000


# ── Helpers ──────────────────────────────────────────────────

def _now():
    """Return current ISO timestamp."""
    return stdlib.time_iso()


def _caps_for_diagnostic(category, diag_name):
    """Build a capabilities dict for a diagnostic based on its category.

    For includes/ diagnostics, we look up by 'includes/<stem>' where stem
    is the filename without extension (or 'includes/memory' for memory/ subdirs).
    Every diagnostic also gets 'me' and 'stdlib'.
    """
    caps = {}

    # Determine the lookup key
    if category == "includes":
        # Strip extension to get the specific key
        stem = diag_name.rsplit(".", 1)[0] if "." in diag_name else diag_name
        # For memory subdirectory diagnostics, use includes/memory
        lookup_key = "includes/" + stem
        if lookup_key not in _CATEGORY_CAPS:
            lookup_key = "includes/memory"
    else:
        lookup_key = category

    cap_names = _CATEGORY_CAPS.get(lookup_key, [])

    # Always include me and stdlib
    all_names = set(cap_names)
    all_names.add("me")
    all_names.add("stdlib")

    for name in all_names:
        obj = _cap_objects.get(name)
        if obj is not None:
            caps[name] = obj

    return caps


def _extract_verify_block(content):
    """Extract the ```python verify ... ``` fenced code block from markdown.

    Returns the code string, or None if no verify block found.
    """
    marker_start = "```python verify"
    marker_end = "```"

    start_idx = content.find(marker_start)
    if start_idx == -1:
        return None

    # Move past the marker line
    code_start = content.index("\n", start_idx) + 1
    # Find closing fence after the code
    end_idx = content.find(marker_end, code_start)
    if end_idx == -1:
        return None

    return content[code_start:end_idx]


# ── Discovery ────────────────────────────────────────────────

def discover_diagnostics():
    """Find all diagnostic files organized by category.

    Uses dir.list() which returns a list of FileSearchResult(id, key).
    Keys are relative to the dir scope prefix (cogs/diagnostics/).

    Returns a dict: { category: [ {name, path, executor} ] }
    """
    diagnostics = {}

    # source is a DirCapability scoped to where this cog's files live
    # (cogos/diagnostics/ in the FileStore)
    all_files = source.list(limit=500)
    if not isinstance(all_files, list):
        print("WARN: source.list() returned unexpected type: " + str(type(all_files)))
        return diagnostics

    # Get the scoped prefix so we can strip it to get relative paths
    prefix = source._scope.get("prefix", "") if hasattr(source, "_scope") else ""

    for entry in all_files:
        key = entry.key if hasattr(entry, "key") else str(entry)

        # Strip prefix to get path relative to diagnostics/
        rel = key
        if prefix and rel.startswith(prefix):
            rel = rel[len(prefix):]

        # Skip root-level files and non-diagnostic files
        if "/" not in rel:
            continue
        if not (rel.endswith(".py") or rel.endswith(".md")):
            continue

        parts = rel.split("/")
        filename = parts[-1]
        if filename in _SKIP_FILES:
            continue

        # Determine category (first directory)
        category = parts[0]

        # For includes/memory/*, category is "includes", name captures subdirectory
        if category == "includes" and len(parts) > 2:
            diag_name = "/".join(parts[1:])
        else:
            diag_name = filename

        executor = "python" if filename.endswith(".py") else "llm"

        if category not in diagnostics:
            diagnostics[category] = []

        diagnostics[category].append({
            "name": diag_name,
            "path": rel,
            "executor": executor,
        })

    return diagnostics


# ── Spawning ─────────────────────────────────────────────────

def spawn_diagnostic(category, diag):
    """Spawn a single diagnostic process.

    Returns (handle, diag_info) or (None, diag_info) on error.
    """
    # Use source.get() which auto-prepends the scoped prefix (cogos/diagnostics/)
    content_result = source.get(diag["path"]).read()
    content = content_result.content if hasattr(content_result, 'content') else None
    if content is None:
        print("WARN: could not read " + diag_path)
        return None, diag

    caps = _caps_for_diagnostic(category, diag["name"])
    proc_name = "diag/" + category + "/" + diag["name"]

    handle = procs.spawn(
        proc_name,
        mode="one_shot",
        content=content,
        executor=diag["executor"],
        capabilities=caps,
    )

    if hasattr(handle, "error"):
        print("WARN: spawn failed for " + proc_name + ": " + str(handle.error))
        return None, diag

    return handle, diag


def spawn_verify(category, diag, verify_code, caps):
    """Spawn a verification process for an .md diagnostic.

    Returns a ProcessHandle or None on error.
    """
    proc_name = "diag/" + category + "/" + diag["name"] + "/verify"

    handle = procs.spawn(
        proc_name,
        mode="one_shot",
        content=verify_code,
        executor="python",
        capabilities=caps,
    )

    if hasattr(handle, "error"):
        print("WARN: verify spawn failed for " + proc_name + ": " + str(handle.error))
        return None

    return handle


# ── Result collection ────────────────────────────────────────

def collect_result(handle, diag, category):
    """Wait for a diagnostic process and collect its result.

    Returns a result dict with name, status, duration_ms, checks, and optional error.
    """
    result = {
        "name": diag["name"],
        "status": "fail",
        "duration_ms": 0,
        "checks": [],
    }

    if handle is None:
        result["error"] = "spawn failed"
        return result

    t0 = time.time()

    # Wait for process to complete
    handle.wait()
    elapsed_ms = int((time.time() - t0) * 1000)
    result["duration_ms"] = elapsed_ms

    # Read stdout/stderr
    # stdout(limit=N) returns: str (limit=1), list[str] (limit>1), or None
    stdout_raw = handle.stdout(limit=100)
    stderr_raw = handle.stderr(limit=100)

    # Normalize to list of strings
    if stdout_raw is None:
        stdout_lines = []
    elif isinstance(stdout_raw, str):
        stdout_lines = [stdout_raw]
    else:
        stdout_lines = stdout_raw

    stderr_text = ""
    if stderr_raw is not None:
        if isinstance(stderr_raw, str):
            stderr_text = stderr_raw
        elif isinstance(stderr_raw, list):
            stderr_text = "\n".join(stderr_raw)

    # Try to parse structured JSON output from stdout
    checks_found = False
    for line in stdout_lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, list):
                result["checks"] = parsed
                checks_found = True
            elif isinstance(parsed, dict) and "checks" in parsed:
                result["checks"] = parsed["checks"]
                checks_found = True
            elif isinstance(parsed, dict) and "status" in parsed:
                result["checks"] = [parsed]
                checks_found = True
        except (ValueError, TypeError):
            pass

    # Determine overall status
    proc_status = handle.status()
    if checks_found:
        all_pass = all(
            c.get("status") == "pass" for c in result["checks"]
        )
        result["status"] = "pass" if all_pass else "fail"
        for c in result["checks"]:
            if c.get("status") == "fail" and "error" not in result:
                result["error"] = c.get("error", "check failed")
    else:
        if proc_status == "completed":
            result["status"] = "pass"
            result["checks"] = [{"name": "run", "status": "pass", "ms": elapsed_ms}]
        else:
            result["status"] = "fail"
            error_msg = "process status: " + str(proc_status)
            if stderr_text.strip():
                error_msg = stderr_text.strip()[:500]
            result["error"] = error_msg
            result["checks"] = [{
                "name": "run",
                "status": "fail",
                "ms": elapsed_ms,
                "error": error_msg,
            }]

    return result


def run_md_verification(handle, diag, category):
    """For .md diagnostics, extract and run the verify block after LLM completes.

    Returns updated checks list and status, or None if no verify block.
    """
    content_result = source.get(diag["path"]).read()
    content = content_result.content if hasattr(content_result, 'content') else None
    if content is None:
        return None

    verify_code = _extract_verify_block(content)
    if verify_code is None:
        return None

    caps = _caps_for_diagnostic(category, diag["name"])

    verify_handle = spawn_verify(category, diag, verify_code, caps)
    if verify_handle is None:
        return {
            "name": "verify",
            "status": "fail",
            "ms": 0,
            "error": "verify process spawn failed",
        }

    t0 = time.time()
    verify_handle.wait()
    elapsed_ms = int((time.time() - t0) * 1000)

    verify_status = verify_handle.status()
    stderr_raw = verify_handle.stderr(limit=50)

    stderr_text = ""
    if stderr_raw is not None:
        if isinstance(stderr_raw, str):
            stderr_text = stderr_raw
        elif isinstance(stderr_raw, list):
            stderr_text = "\n".join(stderr_raw)

    if verify_status == "completed":
        return {"name": "verify", "status": "pass", "ms": elapsed_ms}
    else:
        error_msg = stderr_text.strip()[:500] if stderr_text.strip() else "verification failed"
        return {
            "name": "verify",
            "status": "fail",
            "ms": elapsed_ms,
            "error": error_msg,
        }


# ── Diffing ──────────────────────────────────────────────────

def _flatten_checks(results):
    """Flatten category/diagnostic/check results into a dict keyed by path.

    Returns { "category/diag_name:check_name": check_dict }
    """
    flat = {}
    for cat_name, cat_data in results.get("categories", {}).items():
        for diag in cat_data.get("diagnostics", []):
            for check in diag.get("checks", []):
                key = cat_name + "/" + diag["name"] + ":" + check.get("name", "run")
                flat[key] = check
    return flat


def compute_diff(prev_results, curr_results):
    """Compare previous and current results, return list of changes.

    Each change: { type: FAILING|FIXED|ADDED|REMOVED, key, error? }
    """
    changes = []
    prev = _flatten_checks(prev_results) if prev_results else {}
    curr = _flatten_checks(curr_results)

    all_keys = set(list(prev.keys()) + list(curr.keys()))

    for key in sorted(all_keys):
        in_prev = key in prev
        in_curr = key in curr

        if in_curr and not in_prev:
            changes.append({
                "type": "ADDED",
                "key": key,
            })
        elif in_prev and not in_curr:
            changes.append({
                "type": "REMOVED",
                "key": key,
            })
        elif in_prev and in_curr:
            prev_pass = prev[key].get("status") == "pass"
            curr_pass = curr[key].get("status") == "pass"
            if prev_pass and not curr_pass:
                changes.append({
                    "type": "FAILING",
                    "key": key,
                    "error": curr[key].get("error", ""),
                })
            elif not prev_pass and curr_pass:
                changes.append({
                    "type": "FIXED",
                    "key": key,
                })

    return changes


# ── Report generation ────────────────────────────────────────

def generate_current_md(results):
    """Generate human-readable markdown from results JSON."""
    ts = results.get("timestamp", "")
    epoch = results.get("epoch", "?")
    summary = results.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("pass", 0)

    lines = []
    lines.append("# Diagnostics — " + ts + " (epoch " + str(epoch) + ")")
    lines.append("**" + str(passed) + "/" + str(total) + " PASS** in " + str(results.get("duration_ms", 0)) + "ms")
    lines.append("")

    for cat_name in sorted(results.get("categories", {}).keys()):
        cat = results["categories"][cat_name]
        diags = cat.get("diagnostics", [])
        cat_pass = sum(1 for d in diags if d.get("status") == "pass")
        cat_total = len(diags)
        cat_label = "PASS" if cat.get("status") == "pass" else "FAIL"
        lines.append("## " + cat_name + " (" + str(cat_pass) + "/" + str(cat_total) + " " + cat_label + ")")

        for d in diags:
            check_mark = "[x]" if d.get("status") == "pass" else "[ ]"
            lines.append("- " + check_mark + " " + d["name"] + " (" + str(d.get("duration_ms", 0)) + "ms)")

            # Show individual checks if there are failures
            if d.get("status") == "fail":
                for c in d.get("checks", []):
                    c_mark = "[x]" if c.get("status") == "pass" else "[ ]"
                    lines.append("  - " + c_mark + " " + c.get("name", "?") + " (" + str(c.get("ms", 0)) + "ms)")
                    if c.get("error"):
                        lines.append("    > " + str(c["error"])[:200])

        lines.append("")

    return "\n".join(lines)


def generate_log_entry(results):
    """Generate a log entry for this run."""
    ts = results.get("timestamp", "")
    epoch = results.get("epoch", "?")
    summary = results.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("pass", 0)
    duration = results.get("duration_ms", 0)

    lines = []
    lines.append("## " + ts + " (epoch " + str(epoch) + ") — " + str(passed) + "/" + str(total) + " PASS (" + str(duration) + "ms)")

    # List failures
    failures = []
    for cat_name in sorted(results.get("categories", {}).keys()):
        cat = results["categories"][cat_name]
        for d in cat.get("diagnostics", []):
            for c in d.get("checks", []):
                if c.get("status") == "fail":
                    key = cat_name + "/" + d["name"] + ":" + c.get("name", "run")
                    error = c.get("error", "unknown")
                    failures.append("- FAIL " + key + " — " + str(error)[:200])

    if failures:
        lines.extend(failures)
    else:
        lines.append("(all pass)")

    lines.append("")
    return "\n".join(lines)


def generate_changelog_entry(ts, epoch, changes):
    """Generate changelog entry for state transitions."""
    if not changes:
        return ""

    lines = []
    lines.append("## " + ts + " (epoch " + str(epoch) + ")")
    for ch in changes:
        entry = "- " + ch["type"] + ": " + ch["key"]
        if ch.get("error"):
            entry += " — " + str(ch["error"])[:200]
        lines.append(entry)
    lines.append("")
    return "\n".join(lines)


# ── Data file I/O ────────────────────────────────────────────

def read_previous_results():
    """Read previous current.json from data/diagnostics/."""
    f = data.get("current.json")
    result = f.read()
    if hasattr(result, "error"):
        return None
    try:
        return json.loads(result.content)
    except (ValueError, TypeError):
        return None


def write_results(results, current_md, log_entry, changelog_entry):
    """Write all output files to data/diagnostics/."""
    # Write current.json
    f = data.get("current.json")
    f.write(json.dumps(results, indent=2))

    # Write current.md
    f = data.get("current.md")
    f.write(current_md)

    # Append to log.md
    f = data.get("log.md")
    f.append(log_entry + "\n")

    # Append to changelog.md (only if there are changes)
    if changelog_entry:
        f = data.get("changelog.md")
        f.append(changelog_entry + "\n")


# ── Main ─────────────────────────────────────────────────────

run_start = time.time()
timestamp = _now()
epoch = me.epoch if hasattr(me, "epoch") else 0

print("Diagnostics runner starting at " + timestamp)

# 1. Discover diagnostics
diagnostics = discover_diagnostics()
if not diagnostics:
    print("WARN: no diagnostics found")
    exit()

total_diags = sum(len(v) for v in diagnostics.values())
print("Found " + str(total_diags) + " diagnostics across " + str(len(diagnostics)) + " categories")

# 2. Spawn all diagnostics in parallel
handles = []  # list of (handle, diag, category)
for category, diag_list in diagnostics.items():
    for diag in diag_list:
        handle, d = spawn_diagnostic(category, diag)
        handles.append((handle, d, category))

print("Spawned " + str(len(handles)) + " diagnostic processes")

# 3. Collect results from all processes
category_results = {}
for handle, diag, category in handles:
    result = collect_result(handle, diag, category)

    # For .md diagnostics, run verification after LLM completes
    if diag["executor"] == "llm" and handle is not None:
        verify_check = run_md_verification(handle, diag, category)
        if verify_check is not None:
            result["checks"].append(verify_check)
            # Update overall status: fail if verify failed
            if verify_check.get("status") == "fail":
                result["status"] = "fail"
                if "error" not in result:
                    result["error"] = verify_check.get("error", "verification failed")

    if category not in category_results:
        category_results[category] = []
    category_results[category].append(result)

# 4. Build final results structure
total_checks = 0
total_pass = 0
categories_output = {}

for cat_name in sorted(category_results.keys()):
    diags = category_results[cat_name]
    cat_all_pass = True

    for d in diags:
        for c in d.get("checks", []):
            total_checks += 1
            if c.get("status") == "pass":
                total_pass += 1
        if d.get("status") != "pass":
            cat_all_pass = False

    categories_output[cat_name] = {
        "status": "pass" if cat_all_pass else "fail",
        "diagnostics": diags,
    }

run_duration = int((time.time() - run_start) * 1000)

results = {
    "timestamp": timestamp,
    "epoch": epoch,
    "duration_ms": run_duration,
    "summary": {
        "total": total_checks,
        "pass": total_pass,
        "fail": total_checks - total_pass,
    },
    "categories": categories_output,
}

# 5. Diff against previous run
# Read previous results as late as possible to minimize stale-read window
# if two diagnostic runs overlap.
prev_results = read_previous_results()
changes = compute_diff(prev_results, results)

# 6. Generate reports and write atomically (all writes together)
current_md = generate_current_md(results)
log_entry = generate_log_entry(results)
changelog_entry = generate_changelog_entry(timestamp, epoch, changes)
write_results(results, current_md, log_entry, changelog_entry)

# Summary
print("Diagnostics complete: " + str(total_pass) + "/" + str(total_checks) + " PASS in " + str(run_duration) + "ms")
if changes:
    print("Changes detected: " + str(len(changes)))
    for ch in changes:
        print("  " + ch["type"] + ": " + ch["key"])
else:
    if prev_results is not None:
        print("No changes from previous run")
    else:
        print("First run (no previous results)")
