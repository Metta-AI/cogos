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

scheduler_data = file.read("cogos/lib/scheduler.md")
if hasattr(scheduler_data, 'error'):
    print(f"WARN: scheduler prompt not found: {scheduler_data.error}")
else:
    r = procs.spawn("scheduler",
        mode="daemon",
        content=scheduler_data.content,
        priority=100.0,
        capabilities={"scheduler": None, "channels": None},
        subscribe="system:tick:minute")
    if hasattr(r, 'error'):
        print(f"WARN: scheduler spawn failed: {r.error}")

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
            "stdlib": None, "alerts": None, "email": None, "web": None,
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
