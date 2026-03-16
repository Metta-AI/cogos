# CogOS Init — boot script
# Spawns all infrastructure processes, app daemons, and coglets.

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

discord_prompt = file.read("cogos/io/discord/dispatch.md").content
procs.spawn("discord-handle-message",
    mode="daemon",
    content=discord_prompt,
    priority=10.0,
    model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    capabilities={
        "discord": None, "channels": None, "stdlib": None,
        "procs": None, "file": None, "data:dir": None,
    },
    subscribe=["io:discord:dm", "io:discord:mention", "io:discord:message"])

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

audit_prompt = file.read("apps/secret-audit/orchestrator.md").content
procs.spawn("secret-audit",
    mode="daemon",
    content=audit_prompt,
    priority=4.0,
    capabilities={
        "me": None, "procs": None, "dir": None, "file": None,
        "channels": None, "secrets": None, "stdlib": None,
    },
    subscribe=["secret-audit:requests", "secret-audit:events", "system:tick:hour"])

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
