# CogOS Init — boot script
# Spawns all infrastructure processes, app daemons, and coglets.

# ── Channels (created at boot so handlers can subscribe) ──────
for ch_name in [
    "io:discord:dm", "io:discord:mention", "io:discord:message",
    "system:tick:minute", "system:tick:hour",
    "supervisor:help",
]:
    channels.create(ch_name)

# ── Web request channel (created at boot so handlers can subscribe) ──
channels.create("io:web:request")

# ── Infrastructure ───────────────────────────────────────────

# The dispatcher Lambda already owns matching and dispatch. Do not spawn the
# legacy LLM scheduler daemon here or it can create orphaned runs without
# invoking executors.

supervisor_data = file.read("apps/supervisor/supervisor.md")
if hasattr(supervisor_data, 'error'):
    print(f"WARN: supervisor prompt not found: {supervisor_data.error}")
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
        print(f"WARN: supervisor spawn failed: {r.error}")

# ── Apps are now cogs (created by apply_image from apps/*/init/cog.py) ──

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
