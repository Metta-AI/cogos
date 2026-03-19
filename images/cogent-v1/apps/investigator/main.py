# Investigator daemon — monitors for process failures and alerts,
# spawns LLM coglets to investigate each unique incident.
# Runs in the Python sandbox. All capabilities injected as globals.

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def sanitize_name(s):
    """Sanitize a string for use as a process name component."""
    out = ""
    for c in s:
        if c.isalnum() or c in "-_":
            out += c
        elif c in " .:/" and out and out[-1] != "-":
            out += "-"
    return out[:80].strip("-")


def load_active():
    """Load active investigations from persistent data store."""
    raw = data.get("active.json").read()
    if hasattr(raw, "error"):
        return {}
    try:
        return json.loads(raw.content)
    except (ValueError, TypeError):
        return {}


def save_active(active):
    """Persist active investigations."""
    data.get("active.json").write(json.dumps(active))


# ═══════════════════════════════════════════════════════════
# CLEANUP — remove completed investigations
# ═══════════════════════════════════════════════════════════

def cleanup_completed(active):
    """Remove investigations whose spawned process has finished."""
    to_remove = []
    for dedup_key, proc_name in active.items():
        h = procs.get(name=proc_name)
        if hasattr(h, "error"):
            # Process not found — consider it done
            to_remove.append(dedup_key)
            continue
        if callable(getattr(h, "status", None)):
            st = h.status()
            if st in ("completed", "failed", "disabled"):
                to_remove.append(dedup_key)

    for k in to_remove:
        print("Closing investigation: " + k + " (" + active[k] + ")")
        del active[k]

    return active


# ═══════════════════════════════════════════════════════════
# COLLECT NEW FAILURES
# ═══════════════════════════════════════════════════════════

def collect_failures(active):
    """Query recent failed runs; return list of new incidents to investigate."""
    new_incidents = []
    failed_runs = history.failed(since="5m", limit=50)
    if not isinstance(failed_runs, list):
        print("WARN: history.failed returned " + str(type(failed_runs)))
        return new_incidents

    # Group by process_name (dedup — one investigation per process)
    # history.failed() returns Pydantic RunSummary models with .field_name access
    seen = {}
    for run in failed_runs:
        pname = run.process_name if hasattr(run, "process_name") else ""
        if not pname:
            continue
        # Skip our own investigations
        if pname.startswith("investigator/"):
            continue
        dedup_key = "fail:" + pname
        if dedup_key in active:
            continue
        run_id = run.id if hasattr(run, "id") else str(run)
        run_error = run.error if hasattr(run, "error") else ""
        if dedup_key in seen:
            seen[dedup_key]["run_ids"].append(run_id)
            continue
        seen[dedup_key] = {
            "dedup_key": dedup_key,
            "type": "failure",
            "process_name": pname,
            "run_ids": [run_id],
            "error": (run_error or "")[:500],
        }

    new_incidents.extend(seen.values())
    return new_incidents


# ═══════════════════════════════════════════════════════════
# COLLECT NEW ALERTS
# ═══════════════════════════════════════════════════════════

def collect_alerts(active):
    """Read system:alerts channel for new alerts to investigate."""
    new_incidents = []
    msgs = channels.read("system:alerts", limit=20)
    if not isinstance(msgs, list):
        return new_incidents

    seen = {}
    for msg in msgs:
        body = msg.get("body", msg) if isinstance(msg, dict) else {}
        if not isinstance(body, dict):
            continue
        alert_type = body.get("type", body.get("alert_type", "unknown"))
        source = body.get("source", body.get("process_name", "unknown"))
        dedup_key = "alert:" + str(alert_type) + ":" + str(source)
        if dedup_key in active:
            continue
        if dedup_key in seen:
            continue
        seen[dedup_key] = {
            "dedup_key": dedup_key,
            "type": "alert",
            "alert_type": str(alert_type),
            "source": str(source),
            "message": str(body.get("message", ""))[:500],
        }

    new_incidents.extend(seen.values())
    return new_incidents


# ═══════════════════════════════════════════════════════════
# SPAWN INVESTIGATION COGLETS
# ═══════════════════════════════════════════════════════════

def spawn_investigation(incident, active):
    """Spawn an LLM coglet to investigate an incident."""
    dedup_key = incident["dedup_key"]

    # Read the investigation coglet template
    coglet = file.read("apps/investigator/investigate/main.md")
    if hasattr(coglet, "error"):
        print("ERROR: could not read investigate/main.md: " + str(coglet.error))
        return False

    # Read manager discord ID for DM notifications
    manager_id = ""
    try:
        manager_id = secrets.get("manager_discord_id") or ""
    except Exception as e:
        print("WARN: could not read manager_discord_id secret: " + str(e))

    # Build context prefix
    ctx_lines = [
        "# Investigation Context",
        "",
        "- **Manager Discord ID:** " + manager_id,
        "",
    ]

    if incident["type"] == "failure":
        ctx_lines.append("## Process Failure")
        ctx_lines.append("- **Process:** " + incident["process_name"])
        ctx_lines.append("- **Failed Run IDs:** " + ", ".join(incident["run_ids"]))
        if incident.get("error"):
            ctx_lines.append("- **Error:** " + incident["error"])
        ctx_lines.append("")
    elif incident["type"] == "alert":
        ctx_lines.append("## System Alert")
        ctx_lines.append("- **Alert Type:** " + incident["alert_type"])
        ctx_lines.append("- **Source:** " + incident["source"])
        if incident.get("message"):
            ctx_lines.append("- **Message:** " + incident["message"])
        ctx_lines.append("")

    ctx_lines.append("---")
    ctx_lines.append("")

    content = "\n".join(ctx_lines) + coglet.content

    # Derive process name
    safe_key = sanitize_name(dedup_key)
    proc_name = "investigator/" + safe_key

    r = procs.spawn(
        proc_name,
        mode="one_shot",
        executor="llm",
        content=content,
        capabilities={
            "history": None,
            "channels": None,
            "dir": None,
            "file": None,
            "stdlib": None,
            "discord": None,
            "alerts": None,
            "data:dir": data,
        },
    )

    if hasattr(r, "error"):
        print("ERROR: spawn failed for " + proc_name + ": " + str(r.error))
        return False

    active[dedup_key] = proc_name
    print("Spawned investigation: " + proc_name)
    return True


# ═══════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════

trigger = ""
if event:
    trigger = event.get("channel_name", event.get("type", "unknown"))
print("Investigator woke: " + trigger)

# Load and clean up active investigations
active = load_active()
active = cleanup_completed(active)

# Collect new incidents
new_failures = collect_failures(active)
new_alerts = collect_alerts(active)
all_new = new_failures + new_alerts

if not all_new:
    print("No new incidents. Active investigations: " + str(len(active)))
    save_active(active)
else:
    print("New incidents: " + str(len(all_new)) +
          " (failures=" + str(len(new_failures)) +
          ", alerts=" + str(len(new_alerts)) + ")")

    for incident in all_new:
        spawn_investigation(incident, active)

    save_active(active)

print("Active investigations: " + str(len(active)))
for k, v in active.items():
    print("  " + k + " -> " + v)
