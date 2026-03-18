# CogOS Init — boot script
# Spawns all infrastructure processes, app daemons, and coglets.
# This is the single place that creates all processes, ensuring the
# supervisor channel is available before any cog process starts.

# ── Capability lookup for dynamic spawning ────────────────────
_cap_objects = {
    "me": me, "procs": procs, "dir": dir, "file": file,
    "discord": discord, "channels": channels, "secrets": secrets,
    "stdlib": stdlib, "coglet_factory": coglet_factory, "coglet": coglet,
    "alerts": alerts, "blob": blob, "image": image,
    "asana": asana, "email": email, "github": github,
    "web_search": web_search, "web_fetch": web_fetch, "web": web,
    "cog": cog, "coglet_runtime": coglet_runtime,
}

def _build_caps(cap_list, cog_name):
    caps = {}
    for entry in cap_list:
        if isinstance(entry, str):
            if entry == "cog":
                caps["cog"] = _cap_objects["cog"].scope(cog_name=cog_name)
            else:
                caps[entry] = None
        elif isinstance(entry, dict):
            name = entry["name"]
            alias = entry.get("alias", name)
            config = entry.get("config")
            if config and name in _cap_objects:
                key = str(alias) + ":" + str(name) if alias != name else name
                caps[key] = _cap_objects[name].scope(**config)
            else:
                caps[alias] = None
    return caps

def _spawn_from_spec(spec):
    content_data = file.read(spec["content_file"])
    if hasattr(content_data, 'error'):
        print("WARN: content for " + spec["name"] + " not found: " + str(content_data.error))
        return None
    caps = _build_caps(spec["capabilities"], spec["cog_name"])
    subscribe = spec["handlers"] if spec["handlers"] else None
    r = procs.spawn(
        spec["name"],
        mode=spec["mode"],
        content=content_data.content,
        executor=spec["executor"],
        model=spec.get("model"),
        runner=spec["runner"],
        priority=spec["priority"],
        idle_timeout_ms=spec.get("idle_timeout_ms"),
        capabilities=caps,
        subscribe=subscribe,
        detached=True,
    )
    if hasattr(r, 'error'):
        print("WARN: spawn " + spec["name"] + " failed: " + str(r.error))
        return None
    return r

# ── Read boot manifest ────────────────────────────────────────
manifest_data = file.read("_boot/cog_processes.json")
manifest = []
if hasattr(manifest_data, 'error'):
    print("WARN: boot manifest not found: " + str(manifest_data.error))
else:
    manifest = json.loads(manifest_data.content)

# ── Channels (created at boot so handlers can subscribe) ──────
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "discord-cog:review",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
    "io:web:request",
]:
    channels.create(ch_name)

for proc_spec in manifest:
    for ch_name in proc_spec.get("handlers", []):
        channels.create(ch_name)
    for child_spec in proc_spec.get("children", []):
        for ch_name in child_spec.get("handlers", []):
            channels.create(ch_name)

# ── Infrastructure ───────────────────────────────────────────

# The dispatcher Lambda already owns matching and dispatch. Do not spawn the
# legacy LLM scheduler daemon here or it can create orphaned runs without
# invoking executors.

supervisor_data = file.read("apps/supervisor/supervisor.md")
if hasattr(supervisor_data, 'error'):
    print("WARN: supervisor prompt not found: " + str(supervisor_data.error))
else:
    r = procs.spawn("supervisor",
        mode="daemon",
        content=supervisor_data.content,
        priority=8.0,
        capabilities={
            "me": None, "procs": None, "dir": None, "file": None,
            "discord": None, "channels": None, "secrets": None,
            "stdlib": None, "alerts": None,
            # Delegatable to helpers:
            "asana": None, "email": None, "github": None,
            "web_search": None, "web_fetch": None, "web": None,
            "blob": None, "image": None,
        },
        subscribe="supervisor:help")
    if hasattr(r, 'error'):
        print("WARN: supervisor spawn failed: " + str(r.error))

# ── Cog processes (from boot manifest) ───────────────────────
# Only top-level cog processes are spawned here. Child processes
# (e.g. discord/handler) are the responsibility of their parent cog.

for proc_spec in manifest:
    _spawn_from_spec(proc_spec)

# Kick cog orchestrators so they can set up child processes.
channels.send("discord-cog:review", {"reason": "boot"})

# ── Coglets ──────────────────────────────────────────────────

all_coglets = coglet_factory.list()
for c in all_coglets:
    tendril = coglet.scope(coglet_id=c.coglet_id)
    files = tendril.list_files()
    if "main.md" in files or "main.py" in files:
        tendril.run(procs, capability_overrides={
            "me": None, "procs": None, "dir": None, "file": None,
            "discord": None, "channels": None, "secrets": None,
            "stdlib": None, "coglet_factory": None, "coglet": None,
        })

print("Init complete")
