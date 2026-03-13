# Recruiter app — five processes in a tree.
#
# recruiter (daemon, root) — orchestrator
# recruiter/discover (one-shot, spawned) — batch discovery
# recruiter/present (daemon) — drip-feed candidates to Discord
# recruiter/profile (one-shot, spawned) — deep-dive HTML reports
# recruiter/evolve (one-shot, spawned) — self-improvement

# -- Context engine wiring (includes) --
# These declare which files are injected into each prompt template.
# File content comes from the files/ directory; add_file just sets up includes.

add_file("recruiter/prompts/recruiter.md", content="", includes=[
    "recruiter/criteria.md",
    "recruiter/strategy.md",
])

add_file("recruiter/prompts/discover.md", content="", includes=[
    "recruiter/criteria.md",
    "recruiter/rubric.json",
    "recruiter/sourcer/github.md",
    "recruiter/sourcer/twitter.md",
    "recruiter/sourcer/web.md",
    "recruiter/sourcer/substack.md",
])

add_file("recruiter/prompts/present.md", content="", includes=[
    "recruiter/criteria.md",
    "recruiter/strategy.md",
])

add_file("recruiter/prompts/evolve.md", content="", includes=[
    "recruiter/diagnosis.md",
    "recruiter/criteria.md",
    "recruiter/rubric.json",
    "recruiter/strategy.md",
])

# -- Channels --

add_channel("recruiter:feedback", channel_type="named")

# -- Root orchestrator --
# Daemon that schedules discovery, monitors pipeline, triggers evolution.
# Wakes on hourly ticks and on feedback channel messages.

add_process(
    "recruiter",
    mode="daemon",
    code_key="recruiter/prompts/recruiter.md",
    runner="lambda",
    priority=5.0,
    capabilities=["me", "procs", "dir", "file", "discord", "channels", "secrets"],
    handlers=["system:tick:hour", "recruiter:feedback"],
)

# -- Present daemon --
# Wakes on hourly ticks and presents candidates to Discord.

add_process(
    "recruiter/present",
    mode="daemon",
    code_key="recruiter/prompts/present.md",
    runner="lambda",
    priority=3.0,
    capabilities=["me", "dir", "file", "discord", "channels"],
    handlers=["system:tick:hour"],
)

# Note: recruiter/discover, recruiter/profile, and recruiter/evolve are
# spawned dynamically by the root recruiter process via procs.spawn()
# with scoped capabilities. Their prompts exist as files that the root
# process references when spawning.
