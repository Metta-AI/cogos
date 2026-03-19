from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=100.0,
    emoji="🧠",
    capabilities=[
        "me", "procs", "discord", "channels",
        "secrets", "stdlib", "alerts", "asana", "email", "github",
        "web_search", "web_fetch", "web", "blob", "image",
        "cog_registry", "coglet_runtime", "root_dir",
    ],
    handlers=["supervisor:help", "io:discord:reaction"],
)
