from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    priority=8.0,
    emoji="🧠",
    capabilities=[
        "me", "procs", "file", "discord", "channels",
        "secrets", "stdlib", "alerts", "asana", "email", "github",
        "web_search", "web_fetch", "web", "blob", "image",
        "cog_registry", "coglet_runtime",
        {"name": "dir", "alias": "root"},
    ],
    handlers=["supervisor:help"],
)
