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
    })

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

# ── Apps ─────────────────────────────────────────────────────

nftf_prompt = file.read("apps/newsfromthefront/newsfromthefront.md").content
procs.spawn("newsfromthefront",
    mode="daemon",
    content=nftf_prompt,
    priority=15.0,
    capabilities={
        "me": None, "procs": None, "dir": None, "file": None,
        "channels": None, "discord": None, "web_search": None,
        "secrets": None, "stdlib": None,
    },
    subscribe=[
        "newsfromthefront:tick",
        "newsfromthefront:findings-ready",
        "newsfromthefront:discord-feedback",
        "newsfromthefront:run-requested",
    ])

fib_prompt = file.read("apps/fibonacci/fibonacci.md").content
procs.spawn("fibonacci",
    mode="daemon",
    content=fib_prompt,
    priority=1.0,
    capabilities={"dir": None},
    subscribe="fibonacci:poke")

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
