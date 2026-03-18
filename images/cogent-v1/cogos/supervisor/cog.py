from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=8.0,
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "secrets", "stdlib", "alerts", "asana", "email", "github",
        "web_search", "web_fetch", "web", "blob", "image",
        "cog_registry", "coglet_runtime",
    ],
    handlers=["supervisor:help"],
)
