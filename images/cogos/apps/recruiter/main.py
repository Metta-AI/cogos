# Recruiter — Python Orchestrator
# Dispatches events to LLM worker coglets (discover, present, profile, evolve).
# Config coglet holds static data (criteria, rubric, strategy, sourcer prompts).

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Config coglet — data only, no entrypoint
config = cog.make_coglet("config", files={
    "criteria.md": src.get("criteria.md").read().content,
    "rubric.json": src.get("rubric.json").read().content,
    "strategy.md": src.get("strategy.md").read().content,
    "diagnosis.md": src.get("diagnosis.md").read().content,
    "evolution.md": src.get("evolution.md").read().content,
    "sourcer/github.md": src.get("sourcer/github.md").read().content,
    "sourcer/twitter.md": src.get("sourcer/twitter.md").read().content,
    "sourcer/web.md": src.get("sourcer/web.md").read().content,
    "sourcer/substack.md": src.get("sourcer/substack.md").read().content,
})

# Executable coglets
discover = cog.make_coglet("discover", entrypoint="main.md",
    files={"main.md": src.get("discover.md").read().content})
present = cog.make_coglet("present", entrypoint="main.md", mode="daemon",
    files={"main.md": src.get("present.md").read().content})
profile = cog.make_coglet("profile", entrypoint="main.md",
    files={"main.md": src.get("profile.md").read().content})
evolve = cog.make_coglet("evolve", entrypoint="main.md",
    files={"main.md": src.get("evolve.md").read().content})

# Shared capability set for worker coglets
worker_caps = {
    "me": None, "disk": disk, "config_coglet": config,
    "secrets": None, "discord": None, "channels": None,
    "supervisor": channels.scope(names=["supervisor:help"], ops=["send"]),
}

# Ensure present daemon is running
p = procs.get(name="recruiter/present")
if hasattr(p, "error") or p.status() in ("disabled", "completed"):
    coglet_runtime.run(present, procs,
        capability_overrides=worker_caps,
        subscribe="system:tick:hour")

# Dispatch based on triggering channel
if channel == "recruiter:feedback":
    # Route feedback to the present daemon or evolve
    run = coglet_runtime.run(evolve, procs,
        capability_overrides={
            **worker_caps,
            "discover_coglet": discover,
            "present_coglet": present,
        })
    run.process().send(payload)

elif channel == "system:tick:hour":
    # Periodic tick — check if discovery is needed
    run = coglet_runtime.run(discover, procs,
        capability_overrides=worker_caps)

else:
    print(f"recruiter: unknown channel {channel!r}")
