# CogOS Init — boot script
# Spawns all infrastructure processes, app daemons, and coglets.

# ── Discord channels (created at boot so handlers can subscribe) ──────
for ch_name in ["io:discord:dm", "io:discord:mention", "io:discord:message"]:
    channels.create(ch_name)

# ── Infrastructure ───────────────────────────────────────────

scheduler_prompt = file.read("cogos/lib/scheduler.md").content
procs.spawn("scheduler",
    mode="daemon",
    content=scheduler_prompt,
    priority=100.0,
    capabilities={
        "scheduler/match_channel_messages": None,
        "scheduler/select_processes": None,
        "scheduler/dispatch_process": None,
        "scheduler/unblock_processes": None,
        "scheduler/kill_process": None,
        "channels": None,
    },
    subscribe="system:tick:minute")

supervisor_prompt = file.read("apps/supervisor/supervisor.md").content
procs.spawn("supervisor",
    mode="daemon",
    content=supervisor_prompt,
    priority=8.0,
    capabilities={
        "me": None, "procs": None, "dir": None, "file": None,
        "discord": None, "channels": None, "secrets": None,
        "stdlib": None, "alerts": None, "email": None,
    },
    subscribe="supervisor:help")

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
