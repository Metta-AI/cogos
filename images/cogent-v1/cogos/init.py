# CogOS Init — boot script
# Loads cog manifests and spawns all cog processes.
# Uses raw manifest dicts since the sandbox cannot import Python modules.

# ── Capability lookup for dynamic spawning ────────────────────
_cap_objects = {
    "me": me, "procs": procs, "dir": dir, "file": file,
    "discord": discord, "channels": channels, "secrets": secrets,
    "stdlib": stdlib, "alerts": alerts, "blob": blob, "image": image,
    "asana": asana, "email": email, "github": github,
    "web_search": web_search, "web_fetch": web_fetch, "web": web,
}
# Optional capabilities — may not be injected into init's sandbox
try:
    _cap_objects["cog_registry"] = cog_registry
except NameError:
    pass
try:
    _cap_objects["coglet_runtime"] = coglet_runtime
except NameError:
    pass

def _build_caps(cap_list, cog_name):
    """Build capabilities dict from a CogConfig capabilities list."""
    caps = {}
    for entry in cap_list:
        if isinstance(entry, str):
            # Pass None for unscoped — spawn resolves by name from DB
            caps[entry] = None
        elif isinstance(entry, dict):
            name = entry["name"]
            alias = entry.get("alias", name)
            config = entry.get("config")
            cap_obj = _cap_objects.get(name)
            if cap_obj is not None and config and hasattr(cap_obj, "scope"):
                caps[alias] = cap_obj.scope(**config)
            else:
                caps[alias] = None
    # Add scoped dir and data for cog isolation
    dir_cap = _cap_objects.get("dir")
    if dir_cap is not None and hasattr(dir_cap, "scope"):
        caps["dir"] = dir_cap.scope(prefix="cogs/" + cog_name + "/")
        caps["data"] = dir_cap.scope(prefix="data/" + cog_name + "/")
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
    prefix = manifest.get("content_prefix", "apps")
    content_key = prefix + "/" + cog_name + "/" + entrypoint
    content = _read_file(content_key)
    if not content:
        print("WARN: no content for cog " + cog_name + " at " + content_key)
        return None

    caps = _build_caps(config.get("capabilities", []), cog_name)
    # Add source dir scoped to where the cog's files live in the FileStore
    dir_cap = _cap_objects.get("dir")
    if dir_cap is not None and hasattr(dir_cap, "scope"):
        caps["source:dir"] = dir_cap.scope(prefix=prefix + "/" + cog_name + "/")

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
        print("WARN: spawn " + cog_name + " failed: " + str(r.error))
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
]:
    channels.create(ch_name)

# ── Write cogent profile (editable via dashboard) ────────────
_boot_date = stdlib.time.strftime("%Y-%m-%d")
_profile = file.read("whoami/profile.md")
if hasattr(_profile, 'error'):
    file.write("whoami/profile.md",
        "# Profile\n"
        "\n"
        "- **Name:** (set on boot)\n"
        "- **Discord User ID:** (set on boot)\n"
        "- **Discord Username:** (set on boot)\n"
    )

# ── Read cog manifests ────────────────────────────────────────
manifest_data = file.read("_boot/cog_manifests.json")
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

print("Init complete")
