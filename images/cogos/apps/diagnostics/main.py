# CogOS Diagnostics Orchestrator — spawns child processes per test category.
# Phase 1: spawn children and exit. Phase 2 (next run): collect results.
# Runs in the Python sandbox. All capabilities injected as globals.

import time

def _now():
    t = time.gmtime()
    return (str(t.tm_year) + "-" + str(t.tm_mon).zfill(2) + "-"
            + str(t.tm_mday).zfill(2) + "T" + str(t.tm_hour).zfill(2)
            + ":" + str(t.tm_min).zfill(2) + ":" + str(t.tm_sec).zfill(2) + "Z")

CATEGORIES = {
    "files":    ("files/diag.py",    "python", {"disk": disk}),
    "channels": ("channels/diag.py", "python", {"channels": channels}),
    "me":       ("me/diag.py",       "python", {"me": me}),
    "builtins": ("stdlib/diag.py",   "python", {}),
    "discord":  ("discord/diag.py",  "python", {"discord": discord}),
    "web":      ("web/diag.py",      "python", {"web_fetch": web_fetch, "web_search": web_search}),
    "blob":     ("blob/diag.py",     "python", {"blob": blob}),
    "image":    ("image/diag.py",    "python", {"image": image, "blob": blob}),
    "email":    ("email/diag.py",    "python", {"email": email}),
    "asana":    ("asana/diag.py",    "python", {"asana": asana}),
    "github":   ("github/diag.py",   "python", {"github": github}),
    "alerts":   ("alerts/diag.py",   "python", {"alerts": alerts}),
    "history":  ("history/diag.py",  "python", {"history": history}),
    "spawn":    ("spawn/diag.md",    "llm",    {"procs": procs, "me": me, "disk": disk}),
}

TERMINAL_STATUSES = {"completed", "failed", "disabled", "timeout"}

_channel = event.get("channel_name", "") if event else ""
if _channel != "system:diagnostics":
    pass

else:
    # Check if we already spawned children (phase 2: collect)
    phase_raw = disk.get("_diag/phase.json").read()
    phase_data = None
    if not hasattr(phase_raw, "error"):
        try:
            phase_data = json.loads(phase_raw.content)
        except (ValueError, TypeError):
            pass

    if phase_data and phase_data.get("phase") == "collecting":
        # Phase 2: collect results from children
        timestamp = phase_data["timestamp"]
        spawned_cats = phase_data.get("spawned", [])
        print("Diagnostics phase 2: collecting results at " + timestamp)

        total = 0
        passed = 0
        categories = {}

        for cat in sorted(CATEGORIES):
            checks = []
            if cat not in spawned_cats:
                checks = [{"name": "spawn", "status": "fail", "ms": 0, "error": "child not spawned"}]
            elif cat == "spawn":
                r = disk.get("_diag/spawn/results.json").read()
                if hasattr(r, "error"):
                    h = procs.get(name="_diag/spawn")
                    s = h.status() if not hasattr(h, "error") else "unknown"
                    if s in TERMINAL_STATUSES:
                        runs = h.runs(limit=1) if not hasattr(h, "error") else []
                        err = runs[0].error if runs and runs[0].error else s
                        checks = [{"name": "run", "status": "fail", "ms": 0, "error": str(err)[:300]}]
                    else:
                        checks = [{"name": "run", "status": "fail", "ms": 0, "error": "spawn child not done (status=" + s + ")"}]
                else:
                    try:
                        checks = json.loads(r.content)
                        if not isinstance(checks, list):
                            checks = [{"name": "parse", "status": "fail", "ms": 0, "error": "results not a list"}]
                    except (ValueError, TypeError) as e:
                        checks = [{"name": "parse", "status": "fail", "ms": 0, "error": str(e)[:300]}]
            else:
                h = procs.get(name="_diag/" + cat)
                if hasattr(h, "error"):
                    checks = [{"name": "run", "status": "fail", "ms": 0, "error": "child not found: " + str(h.error)[:200]}]
                else:
                    s = h.status()
                    if s not in TERMINAL_STATUSES:
                        checks = [{"name": "run", "status": "fail", "ms": 0, "error": "timed out (status=" + s + ")"}]
                    else:
                        runs = h.runs(limit=1)
                        if not runs:
                            checks = [{"name": "run", "status": "fail", "ms": 0, "error": "no runs found"}]
                        elif runs[0].error:
                            checks = [{"name": "run", "status": "fail", "ms": 0, "error": str(runs[0].error)[:300]}]
                        elif runs[0].result and isinstance(runs[0].result, dict):
                            output = runs[0].result.get("output", "")
                            if isinstance(output, list):
                                checks = output
                            elif isinstance(output, str):
                                try:
                                    parsed = json.loads(output)
                                    if isinstance(parsed, list):
                                        checks = parsed
                                    else:
                                        checks = [{"name": "run", "status": "fail", "ms": 0, "error": "output parsed but not a list: " + str(type(parsed))}]
                                except (ValueError, TypeError):
                                    checks = [{"name": "run", "status": "fail", "ms": 0, "error": "output not valid JSON: " + output[:200]}]
                            else:
                                checks = [{"name": "run", "status": "fail", "ms": 0, "error": "unexpected output type: " + str(type(output))}]
                        else:
                            checks = [{"name": "run", "status": "fail", "ms": 0, "error": "no result from child"}]

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

        # Diff against previous
        prev = None
        prev_raw = disk.get("current.json").read()
        if not hasattr(prev_raw, "error"):
            try:
                prev = json.loads(prev_raw.content)
            except (ValueError, TypeError):
                pass

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

        disk.get("current.json").write(json.dumps(results))

        md = ["# Diagnostics -- " + timestamp, "**" + str(passed) + "/" + str(total) + " PASS**", ""]
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
                        line += " -- " + str(ck["error"])[:150]
                    md.append(line)
            md.append("")
        disk.get("current.md").write("\n".join(md))

        log_line = "## " + timestamp + " -- " + str(passed) + "/" + str(total) + " PASS"
        log_prev = disk.get("log.md").read()
        log_content = log_prev.content if hasattr(log_prev, "content") else ""
        disk.get("log.md").write(log_line + "\n" + log_content)

        if changes:
            cl_prev = disk.get("changelog.md").read()
            cl_content = cl_prev.content if hasattr(cl_prev, "content") else ""
            disk.get("changelog.md").write("## " + timestamp + "\n" + "\n".join(changes) + "\n\n" + cl_content)

        # Clear phase marker
        disk.get("_diag/phase.json").write("{}")

        print(str(passed) + "/" + str(total) + " passed")
        for c in changes:
            print("  " + c)

    else:
        # Phase 1: spawn children, schedule collection, exit
        timestamp = _now()
        print("Diagnostics phase 1: spawning children at " + timestamp)

        spawned = []
        for cat, (file_key, executor, caps) in sorted(CATEGORIES.items()):
            r = src.get(file_key).read()
            if hasattr(r, "error"):
                print("WARN: could not read " + file_key + ": " + str(r.error))
                continue
            content = r.content
            h = procs.spawn(
                "_diag/" + cat,
                content=content,
                executor=executor,
                mode="one_shot",
                capabilities=caps,
            )
            if hasattr(h, "error"):
                print("WARN: spawn failed for " + cat + ": " + str(h.error))
                continue
            spawned.append(cat)

        # Write phase marker so next run collects
        disk.get("_diag/phase.json").write(json.dumps({
            "phase": "collecting",
            "timestamp": timestamp,
            "spawned": spawned,
        }))

        # Send a delayed trigger to collect results after children finish.
        # The children are one_shot and will complete quickly once dispatched.
        # We send a message to our own channel to wake up for phase 2.
        channels.send("system:diagnostics", {"trigger": "collect", "phase": 2})

        print("Spawned " + str(len(spawned)) + " children, scheduled collection")
