# Recruiter app — one root daemon that spawns all sub-processes.
#
# recruiter (daemon, root) — orchestrator
# recruiter/discover (one-shot, spawned) — batch discovery
# recruiter/present (daemon, spawned) — drip-feed candidates to Discord
# recruiter/profile (one-shot, spawned) — deep-dive HTML reports
# recruiter/evolve (one-shot, spawned) — self-improvement

# -- Channels --

add_channel("recruiter:feedback", channel_type="named")

# -- Root orchestrator --
# Daemon that spawns and manages all sub-processes.
# Wakes on hourly ticks and on feedback channel messages.

add_process(
    "recruiter",
    mode="daemon",
    content="@{apps/recruiter/recruiter.md}",
    runner="lambda",
    priority=5.0,
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels", "secrets", "stdlib",
        {"name": "dir", "alias": "data", "config": {"prefix": "data/recruiter/"}},
    ],
    handlers=["system:tick:hour", "recruiter:feedback"],
)

# All sub-processes (discover, present, profile, evolve) are spawned
# dynamically by the root recruiter process via procs.spawn() with
# scoped capabilities. Their prompts live in apps/recruiter/.
