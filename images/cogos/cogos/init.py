# CogOS Init — boot script
# Loads cog manifests and spawns all cog processes.
# Uses raw manifest dicts since the sandbox cannot import Python modules.

# ── Capability lookup for dynamic spawning ────────────────────
_cap_objects = {
    "me": me, "procs": procs, "root_dir": root_dir, "file": file,
    "channels": channels, "secrets": secrets,
    "stdlib": stdlib, "blob": blob, "image": image,
    "web_search": web_search, "web_fetch": web_fetch, "web": web,
}
# Capabilities that may not be injected into init's sandbox
try:
    _cap_objects["discord"] = discord
except NameError:
    pass
try:
    _cap_objects["alerts"] = alerts
except NameError:
    pass
try:
    _cap_objects["asana"] = asana
except NameError:
    pass
try:
    _cap_objects["email"] = email
except NameError:
    pass
try:
    _cap_objects["github"] = github
except NameError:
    pass
try:
    _cap_objects["cogent"] = cogent
except NameError:
    pass
try:
    _cap_objects["cog_registry"] = cog_registry
except NameError:
    pass
try:
    _cap_objects["coglet_runtime"] = coglet_runtime
except NameError:
    pass
try:
    _cap_objects["history"] = history
except NameError:
    pass
try:
    _cap_objects["monitor"] = monitor
except NameError:
    pass

def _build_caps(cap_list, cog_name):
    """Build capabilities dict from a CogConfig capabilities list.

    Always returns dict(name, Capability) — no aliases, no None values.
    Injects mount-based filesystem capabilities: boot, src, disk, repo.
    """
    caps = {}
    for entry in cap_list:
        if isinstance(entry, str):
            cap_obj = _cap_objects.get(entry)
            if cap_obj is not None:
                caps[entry] = cap_obj
        elif isinstance(entry, dict):
            name = entry["name"]
            cap_type = entry.get("type", name)
            config = entry.get("config")
            cap_obj = _cap_objects.get(cap_type)
            if cap_obj is not None and config and hasattr(cap_obj, "scope"):
                caps[name] = cap_obj.scope(**config)
            elif cap_obj is not None:
                caps[name] = cap_obj
    # Mount-based filesystem capabilities
    dir_cap = _cap_objects.get("root_dir")
    if dir_cap is not None and hasattr(dir_cap, "scope"):
        caps["boot"] = dir_cap.scope(prefix="mnt/boot/", read_only=True)
        caps["src"] = dir_cap.scope(prefix="mnt/boot/" + cog_name + "/", read_only=True)
        caps["disk"] = dir_cap.scope(prefix="mnt/disk/" + cog_name + "/")
        caps["repo"] = dir_cap.scope(prefix="mnt/repo/", read_only=True)
    return caps

def _read_file(key):
    """Read a file from FileStore, returning content or empty string."""
    result = file.read(key)
    if hasattr(result, 'error'):
        print("WARN: file not found: " + key)
        return ""
    return result.content

def _spawn_cog(manifest):
    """Spawn a cog's main process from a manifest dict."""
    config = manifest["config"]
    cog_name = manifest["name"]
    entrypoint = manifest["entrypoint"]

    # Read main content from FileStore
    prefix = manifest.get("content_prefix", "mnt/boot")
    content_key = prefix + "/" + cog_name + "/" + entrypoint
    content = _read_file(content_key)
    if not content:
        print("WARN: no content for cog " + cog_name + " at " + content_key)
        return None

    caps = _build_caps(config.get("capabilities", []), cog_name)

    subscribe = config.get("handlers") if config.get("handlers") else None

    r = procs.spawn(
        cog_name,
        mode=config.get("mode", "one_shot"),
        content=content,
        executor=config.get("executor", "llm"),
        model=config.get("model"),
        runner=config.get("runner", "lambda"),
        priority=config.get("priority", 0.0),
        idle_timeout_ms=config.get("idle_timeout_ms"),
        capabilities=caps,
        subscribe=subscribe,
        detached=True,
    )
    if hasattr(r, 'error'):
        print("ERROR: spawn " + cog_name + " failed: " + str(r.error))
        alerts.error("boot:spawn_failed", "Failed to spawn cog '" + cog_name + "': " + str(r.error))
        return None
    return r

# ── Channels (created at boot so handlers can subscribe) ──────
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "io:discord:api:request", "io:discord:api:response",
    "discord-cog:review",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
    "io:web:request",
    "github:discover",
    "system:diagnostics",
    "system:alerts",
    "supervisor:alerts",
    "triage:proposals",
]:
    channels.create(ch_name)

# ── Write cogent profile from capabilities ────────────────────
_profile_lines = ["# Profile\n"]
for _pname in ["cogent", "discord", "email"]:
    _pcap = _cap_objects.get(_pname)
    if _pcap is not None and hasattr(_pcap, "profile"):
        _profile_lines.append(_pcap.profile())
file.write("mnt/boot/whoami/profile.md", "\n".join(_profile_lines))
_cogent_cap = _cap_objects.get("cogent")
if _cogent_cap is not None and hasattr(_cogent_cap, "name"):
    print("Profile: name=" + _cogent_cap.name)
else:
    print("Profile: written (no cogent capability)")

# ── Read cog manifests ────────────────────────────────────────
manifest_data = file.read("mnt/boot/_boot/cog_manifests.json")
manifests = []
if hasattr(manifest_data, 'error'):
    print("WARN: cog manifests not found: " + str(manifest_data.error))
else:
    manifests = json.loads(manifest_data.content)

# Create channels declared by cog handlers before spawning
for m in manifests:
    config = m["config"]
    for ch_name in config.get("handlers", []):
        channels.create(ch_name)
    for cl_name, cl_data in m.get("coglets", {}).items():
        cl_config = cl_data.get("config", {})
        for ch_name in cl_config.get("handlers", []):
            channels.create(ch_name)

# ── Spawn cog processes ───────────────────────────────────────
for m in manifests:
    result = _spawn_cog(m)
    if result is not None:
        print("Started cog: " + m["name"])

# Kick cog orchestrators so they can set up child processes.
channels.send("discord-cog:review", {"reason": "boot"})
channels.send("system:tick:hour", {"reason": "boot"})

# Run diagnostics on boot
channels.send("system:diagnostics", {"reason": "boot"})

print("Init complete")
