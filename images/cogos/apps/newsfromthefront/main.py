# Newsfromthefront — Python Orchestrator
# Dispatches events to LLM worker coglets (researcher, analyst, test, backfill).

channel = event.get("channel_name", "")
payload = event.get("payload", {})

# Create/get coglets (idempotent)
researcher = cog.make_coglet("researcher", entrypoint="main.md",
    files={"main.md": src.get("researcher.md").read().content})
analyst = cog.make_coglet("analyst", entrypoint="main.md",
    files={"main.md": src.get("analyst.md").read().content})
test_runner = cog.make_coglet("test", entrypoint="main.md",
    files={"main.md": src.get("test.md").read().content})
backfiller = cog.make_coglet("backfill", entrypoint="main.md",
    files={"main.md": src.get("backfill.md").read().content})

caps = {
    "web_search": None, "channels": None,
    "discord": None, "secrets": None, "stdlib": None,
    "disk": disk,
}

if channel == "newsfromthefront:tick":
    coglet_runtime.run(researcher, procs, capability_overrides=caps)

elif channel == "newsfromthefront:findings-ready":
    run = coglet_runtime.run(analyst, procs, capability_overrides=caps)
    run.process().send(payload)

elif channel == "newsfromthefront:discord-feedback":
    run = coglet_runtime.run(analyst, procs, capability_overrides=caps)
    run.process().send(payload)

elif channel == "newsfromthefront:run-requested":
    mode = payload.get("mode")
    if mode == "test":
        run = coglet_runtime.run(test_runner, procs, capability_overrides=caps)
        run.process().send(payload)
    elif mode == "backfill":
        run = coglet_runtime.run(backfiller, procs, capability_overrides=caps)
        run.process().send(payload)

else:
    print(f"newsfromthefront: unknown channel {channel!r}")
