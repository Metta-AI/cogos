from cogos.cog.cog import CogConfig

config = CogConfig(
    mode="daemon",
    executor="python",
    priority=100.0,
    handlers=["system:diagnostics"],
    capabilities=[
        "me", "procs",
        "channels", "stdlib", "history",
        "discord", "email", "asana", "github",
        "web", "web_search", "web_fetch",
        "blob", "image", "alerts",
    ],
)
